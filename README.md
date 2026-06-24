# AgentHub Voice

Mobile voice command app for AgentHub.

This public repository hosts only the phone web app. It does not contain a
GitHub token, private task data, or machine secrets.

## Pages Setup

In this repository, open:

```text
Settings -> Pages
```

Then choose:

```text
Source: Deploy from a branch
Branch: main
Folder: / (root)
```

The expected app URL is:

```text
https://pauldw666.github.io/agenthub-voice/
```

## Phone Use

1. Open the app URL on the phone.
2. Paste a fine-grained GitHub token.
3. Keep the defaults:
   - Owner: `Pauldw666`
   - Repo: `codex-agenthub`
   - Branch: `main`
4. Tap `保存设置`.
5. Choose `自动判断`, `Win`, `Mac`, or `两边`.
6. Tap `开始语音`, speak the task, review the text, then tap `提交任务`.

The app writes a Quick Command to the private AgentHub repository's
`MOBILE_INBOX.md`. The Windows/Mac AgentHub workers then import and process it.

## Token Scope

Use a fine-grained personal access token with:

- Repository access: only `Pauldw666/codex-agenthub`
- Permissions:
  - Contents: Read and write
  - Metadata: Read-only

Do not paste the token into chat or commit it to any repository. The app stores
it only in the phone browser's local storage.
