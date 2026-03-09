/**
 * Cloudflare Email Worker — routes inbound emails to cogent ingest endpoints.
 *
 * Deployed once for the whole domain. Uses Workers KV to map recipient
 * local parts to cogent ingest URLs.
 *
 * KV entries:
 *   ovo   -> https://ovo.softmax-cogents.com/api/ingest/email
 *   alpha -> https://alpha.softmax-cogents.com/api/ingest/email
 *
 * Bindings required:
 *   - COGENT_ROUTES: KV namespace
 *   - INGEST_SECRET: secret (string)
 */

/**
 * Extract the text/plain body from a raw MIME email.
 * Handles both simple text emails and multipart messages.
 */
function extractTextBody(rawEmail) {
  // Check for multipart boundary
  const boundaryMatch = rawEmail.match(/boundary="?([^\s"]+)"?/i);
  if (!boundaryMatch) {
    // Not multipart — find body after blank line
    const blankLine = rawEmail.indexOf("\r\n\r\n");
    if (blankLine === -1) {
      const blankLineLf = rawEmail.indexOf("\n\n");
      return blankLineLf === -1 ? "" : rawEmail.slice(blankLineLf + 2);
    }
    return rawEmail.slice(blankLine + 4);
  }

  const boundary = boundaryMatch[1];
  const parts = rawEmail.split("--" + boundary);

  for (const part of parts) {
    // Look for text/plain content type
    if (/content-type:\s*text\/plain/i.test(part)) {
      const bodyStart = part.indexOf("\r\n\r\n");
      if (bodyStart !== -1) {
        return part.slice(bodyStart + 4).trim();
      }
      const bodyStartLf = part.indexOf("\n\n");
      if (bodyStartLf !== -1) {
        return part.slice(bodyStartLf + 2).trim();
      }
    }
  }

  // Fallback: return empty if no text/plain found
  return "";
}

export default {
  async email(message, env, ctx) {
    const to = message.to;
    const from = message.from;
    const localPart = to.split("@")[0];

    // Read raw email stream
    const rawEmail = await new Response(message.raw).text();

    // Parse headers
    const subject = message.headers.get("subject") || "(no subject)";
    const messageId = message.headers.get("message-id") || "";
    const date = message.headers.get("date") || "";

    // Extract text body
    const body = extractTextBody(rawEmail);

    // Look up cogent ingest URL from KV
    const ingestUrl = await env.COGENT_ROUTES.get(localPart);
    if (!ingestUrl) {
      message.setReject(`Unknown recipient: ${localPart}`);
      return;
    }

    const payload = {
      event_type: "email:received",
      source: "cloudflare-email-worker",
      payload: {
        from: from,
        to: to,
        subject: subject,
        body: body,
        message_id: messageId,
        date: date,
        cogent: localPart,
      },
    };

    const resp = await fetch(ingestUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.INGEST_SECRET}`,
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      // CF Email Routing will retry on error
      throw new Error(`Ingest failed: ${resp.status} ${await resp.text()}`);
    }
  },
};
