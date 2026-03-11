const AWS_REGION = "us-east-1";
const LOG_WINDOW_MS = 60 * 60 * 1000;

function encodeInsightsValue(value: string): string {
  return encodeURIComponent(value).replace(/%/g, "*");
}

function executorLogGroups(cogentName: string, runner: string | null | undefined): string[] {
  const safeName = cogentName.replace(/\./g, "-");
  const lambdaGroup = `/aws/lambda/cogent-${safeName}-executor`;
  const ecsGroup = `/ecs/cogent-${safeName}-executor`;

  if (runner === "ecs") return [ecsGroup, lambdaGroup];
  if (runner === "lambda") return [lambdaGroup, ecsGroup];
  return [lambdaGroup, ecsGroup];
}

function parseCreatedAtMillis(createdAt: string | null): number {
  if (!createdAt) return Number.NaN;

  let normalized = createdAt.trim();
  if (normalized.includes(" ") && !normalized.includes("T")) {
    normalized = normalized.replace(" ", "T");
  }
  if (!/[zZ]|[+-]\d{2}:\d{2}$/.test(normalized)) {
    normalized += "Z";
  }

  return Date.parse(normalized);
}

function buildTimeRangeFragment(createdAt: string | null): string {
  const timestamp = parseCreatedAtMillis(createdAt);
  if (!Number.isFinite(timestamp)) {
    return "start~-3600~timeType~'RELATIVE~unit~'seconds";
  }

  const start = Math.max(timestamp - LOG_WINDOW_MS, 0);
  const end = Math.max(timestamp + LOG_WINDOW_MS, Date.now());
  return `start~${start}~end~${end}~timeType~'ABSOLUTE`;
}

function buildSourceFragment(logGroups: string[]): string {
  const groups = logGroups.map((logGroup) => `~'${encodeInsightsValue(logGroup)}`).join("");
  return `source~(${groups})`;
}

export function buildCogentRunLogsUrl(
  cogentName: string,
  runId: string,
  createdAt: string | null,
  runner?: string | null,
): string {
  const logGroups = executorLogGroups(cogentName, runner);
  const query = [
    "fields @timestamp, @message, @logStream, run_id",
    `| filter run_id = "${runId}" or @message like /${runId}/`,
    "| sort @timestamp asc",
  ].join("\n");
  const fragment = [
    buildTimeRangeFragment(createdAt),
    `editorString~'${encodeInsightsValue(query)}`,
    buildSourceFragment(logGroups),
  ].join("~");

  return (
    `https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}` +
    `#logsV2:logs-insights$3FqueryDetail$3D~(${fragment})`
  );
}
