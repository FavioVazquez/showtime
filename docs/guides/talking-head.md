# Dress up a talking head

You have a clip of someone talking: a founder update, a lecture, an interview. You want it to look produced
without touching the footage: a name tag, a number that counts up, a pull-quote, a list that builds as it is said,
captions with the key words in colour, and maybe one big word behind the speaker. This guide shows what to say
and what your agent does.

## Say this

> "Dress up interview.mp4: a name tag, a data callout, a pull-quote and captions with emphasis. A 16:9 cut and a
> 9:16 cut."

Add the speaker's name and role if the clip does not say them. Every name, number and label on screen comes
from the speaker's words or from what you give.

## What happens

Your agent runs these, in this order:

1. `showtime job init interview --platform youtube` makes the job folder.
2. `showtime transcribe interview.mp4 --edit-dir <job>/edit` writes a word-level transcript, on your machine.
3. `showtime edit cut <job>/edit/transcripts/interview.json -o <job>/edit/edl.json` drops the ums and the long
   pauses. The edit is a JSON file (an EDL), so nothing touches your footage.
4. `showtime edit cards suggest <job>` lists moments for cards: numbers with units, names, lists, quotable lines,
   stressed words. Your agent picks 4-7 for a minute and writes them into the EDL, each anchored to a phrase.
5. `showtime edit check <job>/edit/edl.json` prints each card's times and any problem (too short to read, over
   the face, under the captions).
6. For 9:16 it copies the EDL with `"output": {"aspect": "9:16"}` and checks it again. A card with no room
   becomes a split: the speaker moves to the lower part of the frame.
7. `showtime edit render <job>/edit/edl.json --preview`, then stills with `showtime snap`, and one band per card
   with `showtime edit view`.
8. The finals with `showtime edit render`, then `showtime qa` on each file.

Cards follow the words, so a later re-cut moves them with the words. A word behind the speaker is a card too
(`"type": "behind"`): the render cuts the speaker out of the frame on the CPU and puts the word between the
background and the person.

## What you get

- `final.mp4` (16:9) and `final-9x16.mp4`, each with an `.srt` beside it.
- The EDLs in `<job>/edit/`, which you or your agent can edit and render again.
- Contact sheets and card bands to look at.

## How long it takes

Measured for [example 23](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/23-talking-head-cards-nasa) (a 69 s interview) on a 6-core Intel Mac
that other jobs kept busy:

| Step | Time |
|---|---|
| Transcribe 69 s of audio | 38 s |
| `edit cards suggest` | a few seconds |
| Previews at 720p | 150-310 s each |
| Finals, 16:9 / 9:16 | 422 s / 555 s |
| `qa`, 16:9 / 9:16 | 57 s / 43 s |

The cards are rendered once and cached, so a re-cut that keeps their text reuses them. The cut-out for a word
behind the speaker takes about 1.3-1.8 minutes per minute of 1080p footage on a 64-core Linux machine with no
GPU, and about 5.7 minutes when it is held to 6 of its cores (`footage cutout`, measured).

## Phrases that change it

- "Put the word *Faster* behind her when she says it" adds a behind card.
- "Use the tidewater look" (or any id from `showtime signature`) sets the cards' colours and type.
- "Clean captions" or "bold captions" picks the caption style.
- "Only the 9:16 cut" skips the wide one.
- "No captions over her face" is already the default once there are cards.

## Limits

- The speaker's face is found by a face detector. Two people in one shot, or a wide shot, can confuse it.
- The cut-out is made for people, not objects. Fine hair over a new background can lose strands.
- A behind word in 9:16 often sits partly under the head: qa warns when too much of it is hidden.
- Cards need words to anchor to. A silent stretch cannot carry one.

## The example

[Example 23](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/23-talking-head-cards-nasa): a NASA interview dressed with seven cards, in 16:9
and 9:16, with the word "Faster" behind the speaker. The full rules are in
[editing.md, section 9](../../skills/showtime/references/editing.md).
