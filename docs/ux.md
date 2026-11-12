# UX notes and usability script

## Goals

- Server: deploy + first subscription in under 15 minutes for a new user.
- Client: import + connect in under 5 minutes.
- Common actions within three clicks; keyboard users can do the same with
  shortcuts.
- No dead ends: every error has at least one recovery action.

## First-run flows

**Server:** account → deployment/domain → default inbound (Reality recommended)
→ review. The last step creates the admin and opens the console with Reality
already listening.

**Client:** account → import (URL/share link/QR) → test → mode. System proxy is
the recommended first mode; TUN is presented as “global mode” with its
permission and kill-switch caveats.

## Interaction rules

- Feedback is immediate: buttons enter pending, success uses a 4s toast, errors
  persist and can be copied.
- Forms validate on blur; errors appear next to the field; leaving with unsaved
  changes prompts.
- Tables have sticky headers, hover, selection, column/density controls and
  card layouts on phones. Filters live in the URL.
- Detail views use a right drawer; confirmations use a dialog; never nest
  dialogs.
- Long jobs never block the page. The job drawer is reachable from the topbar.
- Theme and language changes apply without a reload.
- Status changes are announced through `aria-live`.

## Keyboard

`Cmd/Ctrl+K` command palette, `/` focus search, `?` shortcuts, `C` connect on
client, `G` then `D/U/C/R/L/S` navigate, `Esc` close. All interactive elements
are reachable by Tab with a 3px focus ring.

## Usability test (5 participants)

1. Give a fresh Ubuntu VPS and the release assets. Task: install, create one
   user, open the subscription on a phone. Target ≤15 minutes, no hints.
2. Give a clean Windows laptop with the installer. Task: import the URL, connect,
   verify traffic, switch to TUN, disconnect. Target ≤5 minutes.
3. Observe where participants hesitate; record task success, time, and any
   accessibility issue. Fix blockers before release.

Success threshold: ≥90% task completion; no participant blocked by a bug; all
serious/critical axe findings fixed.
