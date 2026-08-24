# Content CLI lifecycle

Launcher installs one `ctx9-content` command from the Content repository's reproducible `v2.0.0` archive. The catalog pins its URL and SHA-256. Content owns login, doctor, API behavior, installation, verification, and uninstall.

Acceptance is:

```bash
ctx9 install ctx9-content
ctx9 doctor ctx9-content
ctx9-content --version
ctx9 uninstall ctx9-content
```

The former File Upload and Artifacts CLI components are not aliases or independent catalog entries. Their repositories and old data remain intact until the separately approved production cutover and retirement steps.
