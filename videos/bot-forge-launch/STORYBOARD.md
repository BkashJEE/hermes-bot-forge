---
format: 1080x1080
duration: 16s
message: "The bot that builds bots is in the Hermes plugin catalog"
arc: Callback → Proof → Command → Close
audience: Hermes Agent builders on X, quote-posted onto the author's own Sep 17 thread
mode: autonomous
music: none
---

## Frame 1 — The callback

- scene: The September claim, restated in one line, then answered
- duration: 3.5s
- poster: 2.5s
- transition_in: cut
- src: compositions/frames/01-callback.html
- status: animated
- assets: assets/icon.png
- blueprint: titlecard-reveal

Opens cold on the claim this video answers. A dated kicker — `SEP 17` in mono — sits above the
line "I built a bot that builds bots." Then the answer lands under it, in cyan: "It's in the
catalog now." No product explanation: the post this quotes already showed the thing working.

The bot mark sits small and steady in the corner from the first frame so the tour that follows
is visibly the same product.

Shot sequence
- 0.0–0.6s — `SEP 17` kicker (mono, cyan-dim, 0.16em tracking) fades up at top-left of the type block.
- 0.3–1.4s — "I built a bot that builds bots." rises 24px and fades in, one line, display scale.
- 1.4–1.6s — a 1px ink@20% hairline draws left-to-right under it, 320px wide.
- 1.6–2.6s — "It's in the catalog now." fades up beneath the rule in cyan — the frame's one voltage.
- 0.8s onward — the mark fades to 0.9 opacity, bottom-left, 96px, and holds still for the rest.
- 3.2–3.5s — everything holds; no exit animation, the cut does the work.

asset_candidates: assets/icon.png — the mark, small, bottom-left, present but not the subject.

## Frame 2 — The page itself

- scene: The real catalog page travels up past the listing, tier, version and stars
- duration: 6s
- poster: 3s
- transition_in: crossfade
- src: compositions/frames/02-page.html
- status: animated
- assets: assets/catalog-full-page.png
- blueprint: transcript-scroll-artifact-reveal

The proof beat, and the longest. The genuine page at
hermes-agent.nousresearch.com/docs/plugins/bot-forge fills the square, cropped to its readable
column, and travels upward at a steady, readable pace — the hero banner, then the listing row,
then what it adds. Nothing is rebuilt: this is the captured page.

One cyan hairline ring draws itself around the `Community · v0.5.0 · ★ 29` row as it passes, holds
while the eye lands, then releases. A mono caption sits in the lower band throughout:
`hermes-agent.nousresearch.com/docs/plugins/bot-forge` — so a viewer who screenshots the frame
still has the address.

Shot sequence
- 0.0–0.5s — the page plate fades in from black already at its start position (top of the page).
- 0.0–5.2s — the plate travels upward at a constant rate, no easing, covering the hero banner,
  the listing row and the start of "What it adds". Motion never stops mid-frame.
- 1.6–2.0s — a cyan 2px ring draws itself around the `Community · v0.5.0 · ★ 29` row as that row
  reaches the upper third; it tracks the row while the page keeps moving.
- 2.0–3.2s — the ring holds at full opacity.
- 3.2–3.6s — the ring fades out; nothing replaces it.
- 0.4s onward — the mono address caption fades up in the lower band and holds to the end.

asset_candidates: assets/catalog-full-page.png — the 1920×12344 full-page plate; the scroll is a
viewport travelling down it, never a rebuild of the page.

handoff_out: the page plate at scale 1.0, opacity 1, still travelling upward at its constant rate;
the cyan ring released; the mono address caption at opacity 1 in the lower band.

## Frame 3 — The command

- scene: The install line, alone, big enough to read on a phone
- duration: 3.5s
- poster: 2.2s
- transition_in: crossfade
- src: compositions/frames/03-command.html
- status: animated
- assets: assets/catalog-page.png
- blueprint: typewriter-reveal

handoff_in: the page plate arrives at scale 1.0, opacity 1, still travelling upward at the same
rate, then settles and dims back to 18% behind the command chip — no jump at the cut.

The one thing a viewer might act on. The install command sits in a mono chip, centred, large:

    hermes plugins install bot-forge

The page continues behind it, heavily dimmed, so the command is clearly *from* that page. A single
caret blinks once at the end of the line and stops — one blink, not a loop; it says "terminal"
without becoming an animation.

Shot sequence
- 0.0–0.5s — the inherited page settles from its travel and dims to 18% behind a near-black scrim.
- 0.3–1.0s — the mono chip scales up from 0.96 with its 1px cyan-dim border, centred.
- 0.5–1.2s — `hermes plugins install bot-forge` types on in one smooth reveal (a clip-path wipe,
  left to right — not a character-by-character stutter).
- 1.2–1.5s — the caret blinks once at the end of the line, then stays off.
- 1.5–3.5s — the chip holds dead still, long enough to read and screenshot.

asset_candidates: assets/catalog-page.png — the page hero, dimmed to a backdrop.

## Frame 4 — Close

- scene: Mark, name, and where it lives
- duration: 3s
- poster: 2s
- transition_in: crossfade
- src: compositions/frames/04-close.html
- status: animated
- assets: assets/icon.png
- blueprint: logo-assemble-lockup

The mark moves from the corner to centre and grows into the close — the same object the video
opened with, now the subject. Under it: **Bot Forge**, then one mono line,
`github.com/BkashJEE/hermes-bot-forge`, and a single cyan rule.

No call to action beyond the address. The command was the ask; this is the signature.

Shot sequence
- 0.0–0.8s — the mark travels from the lower-left corner to centre and scales 96px → 220px.
- 0.8–1.4s — "Bot Forge" fades up beneath it at display scale.
- 1.3–1.7s — a 2px cyan rule draws outward from centre to 200px wide.
- 1.6–2.2s — `github.com/BkashJEE/hermes-bot-forge` fades up in mono under the rule.
- 2.2–3.0s — the whole lockup holds; the last half second is still.

asset_candidates: assets/icon.png — the mark, centred, the frame's focal.

## Video direction

Dark throughout: `cream` #070B13 is the paper, `ink` #F1F5F9 the type, cyan #22D3EE the single
scarce voltage — one cyan element per frame, never two. Inter for display, JetBrains Mono for
every address, command and kicker.

Motion is calm and mechanical, never bouncy: the page travels at a constant rate, type arrives by
a short rise and fade, and the only easing that draws attention is the ring on Frame 2. Nothing
spins, nothing scales for emphasis except the mark's single growth into the close.

Silent by design — it autoplays muted in the feed, so every word is on screen and nothing depends
on sound.
