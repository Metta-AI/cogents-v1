
checks = []

try:
    if email is None:
        ms = 0
        checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": "email capability is None"})
    else:
        # Verify the capability object exists and has methods
        has_methods = len([m for m in dir(email) if not m.startswith("_")]) > 0
        ms = 0
        if has_methods:
            checks.append({"name": "email_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": "no methods found on email capability"})

        # Verify address is auto-configured
        addr = email.addresses()
        if addr and "@" in addr:
            checks.append({"name": "email_address", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "email_address", "status": "fail", "ms": 0, "error": "no valid address: " + repr(addr)})

        # Test receive (read-only)
        try:
            msgs = email.receive(limit=5)
            if isinstance(msgs, list):
                checks.append({"name": "email_receive", "status": "pass", "ms": 0})
            else:
                checks.append({"name": "email_receive", "status": "fail", "ms": 0, "error": "receive returned " + str(type(msgs))})
        except Exception as e:
            checks.append({"name": "email_receive", "status": "fail", "ms": 0, "error": str(e)})

except Exception as e:
    ms = 0
    checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
