# Erratum: video script and presentation guide

Live app: https://erratum-nine.vercel.app · Hard deadline: **1:00 PM EDT**. Submit the Devpost text first (paste from `SUBMISSION.md`; you can edit until the deadline), then record and add the video link.

**The one idea to land: AI reads, code decides.**

## 1. Spending limits (5 min, do first)
- **Nebius:** console → **Billing → Budgets → Create budget**. Set a small amount (for example, your hackathon credit) with alerts at 50% and 100%.
  - Budgets only **email** you. They don't block spending, and the usage data updates every few hours.
  - The real hard stop: don't top up beyond the hackathon credit, and **delete or rotate the key after judging** (then update it in Vercel).
- **Tavily:** app.tavily.com.
  - The free plan (1,000 credits a month) is already a hard cap: the API just stops with error 432.
  - If you turned on pay-as-you-go, set its limit in the dashboard (error 433 when reached).
  - One Erratum audit with a registry link uses about 2 credits.

## 2. The one idea the video must land
**"AI reads, code decides."** A judge should finish the video able to repeat these three things:
1. **The problem is real:** the ×10 spatula slip passed peer review, and about half of psychology papers have a p-value mismatch.
2. **The split is the insight:** Nemotron finds the numbers, and code checks every one. The model never makes a verdict.
3. **You proved it and learned something:** 20 of 20 planted errors caught. Code also rejects numbers the AI can't show in its own quote, which was learned from real false alarms.

Point 3 is what shows *real understanding*. Anyone can demo; few can explain what broke and why their fix is structural.

## 3. Word-for-word script (about 410 words, about 2:50 at a calm pace)
Have these open before recording:
- Tab 1: https://erratum-nine.vercel.app
- Tab 2: the GitHub README (architecture table and the Evaluation table)

| Time | On screen | Say |
|---|---|---|
| 0:00 | Click **The black-spatula calculation**; the quote appears | "In 2024, a study of black plastic kitchen utensils made headlines. Its safety math said sixty kilograms times seven thousand nanograms per kilogram equals forty-two thousand. The real answer is four hundred twenty thousand. That ten-times slip passed peer review." |
| 0:20 | Scroll back to the top of the homepage | "It's not rare. Statcheck found about half of psychology papers contain a p-value that doesn't match its own test. GRIM found impossible averages in 36 of 71 papers. And asking a chatbot to find the errors doesn't work: models are bad at arithmetic, and you can't tell their real catches from their false alarms." |
| 0:40 | Hover over the tagline | "So Erratum splits the job. Nemotron reads the paper and finds every number that can be recomputed. Code does the math and makes every decision." |
| 0:50 | Spatula report: point at the red flag, then Ultra's box | "Code recomputes four hundred twenty thousand and flags it: off by exactly ten times, and it could change the conclusion. Nemotron Ultra explains the impact and drafts a polite question to the authors, clearly labeled unverified." |
| 1:10 | Click **Planted-error paper** and scroll the flags | "This test paper has five planted errors, and Erratum finds all five: a p-value on the wrong side of point-oh-five, a ten-times cost slip, two wrong percentages, and an average that's impossible for 17 people on a 1-to-7 scale. And this t-test is *not* flagged: it only works if one-tailed, so Erratum says exactly that instead of accusing." |
| 1:35 | Click **Preregistration cross-check** | "On a real paper, every checkable number holds up. Tavily reads its preregistration on OSF, and code compares the plan with what was reported. When the registry doesn't say, Erratum says 'unclear' instead of guessing." |
| 1:55 | Tab 2: README architecture table | "Everything runs on Nebius Token Factory. Nemotron 3.5 Lightning extracts the numbers with thinking switched off, so it's fast and cheap. Nemotron 3 Super explains each flag. Nemotron 3 Ultra only runs when a conclusion could change. A full paper takes under a minute and ten to thirty thousand tokens." |
| 2:20 | Report footer: "Grounding: code set aside N numbers…" | "Our hardest bug wasn't the math. On real papers, Nemotron read seventy-two percent as seventy-two out of two hundred forty, and turned 'p less than point-oh-five' into 'equals'. Plausible, and wrong. So code now rejects any number the model can't show in its own quote." |
| 2:40 | README Evaluation table | "On twenty real papers with planted errors, Erratum caught twenty of twenty, and so did Nemotron Ultra alone. The difference: our checks cost zero model tokens and show their math, while Ultra alone also flagged numbers that were actually correct." |
| 2:55 | Back to the homepage | "Erratum: Nemotron reads the paper, math checks every number. A flag isn't an accusation; it's a number worth a second look." |

## 4. Recording, step by step (about 40 min)
1. **Set up (5 min):**
   - Chrome, light mode, zoom 125% (Ctrl/Cmd +), only the two tabs open, notifications off.
   - Click each demo once. They're cached, so they appear instantly.
2. **Recorder:**
   - **Loom** is the easiest: screen plus voice, instant link.
   - Mac: Cmd+Shift+5, or QuickTime. Windows: Clipchamp, or Win+Alt+R (Xbox Game Bar).
   - Use any headset mic in a quiet room.
3. **Record in segments, one per row above.** If you stumble, redo that row only. Speak slower than feels natural and pause about 1 second after each number. Move the mouse to whatever you're talking about.
4. **Edit (10 min):**
   - Join the clips in CapCut, Clipchamp or iMovie, and cut the dead air.
   - Keep it **under 3:00**; judges stop watching.
   - Turn on auto-captions.
5. **Publish (5 min):**
   - Upload to YouTube as **Public** or **Unlisted**, whichever Devpost's rules allow.
   - Paste the link into Devpost and save.
6. **Check:** watch it once, with sound, start to finish.

## 5. If you present live to judges
- Use the same 10 beats. The live twist: on the **Paper ID** tab, type `PMC13354088` and press **Check the numbers**. Then explain the architecture (beat 1:55) while it runs for about 30–50 seconds. This uses up the waiting time and proves the app is live.
- If the network fails, click a demo. They never depend on the API.
- End on the one idea: **"AI reads, code decides."**

## 6. Judge questions: short, honest answers
- **"Why not just ask an LLM?"** "We tested that. Ultra alone also caught 20/20, but it used about 18k tokens per paper on the biggest model, gave different answers on different runs, and flagged correct numbers, such as a Holm adjustment it got wrong. Our checks cost zero tokens and show the math."
- **"How do you avoid false accusations?"** "A missing fact means 'not checkable', never a flag. Every AI number must appear in its own quote. AI text is labeled unverified, the wording stays neutral, and the demos use only corrected or synthetic papers."
- **"Why three Nemotron models?"** "Cost tiers. Lightning does the bulk extraction with thinking off; Super explains; Ultra only runs on conclusion-changing flags."
- **"What does Tavily do?"** "It reads the registry page (OSF, ClinicalTrials.gov). Nemotron quotes the planned sample size, and code checks that quote is really on the page and compares it. Exceeding a planned *minimum* isn't a mismatch."
- **"What can't it do yet?"** "Tables, figures and supplements; unusual number formats; papers with several studies, where 'the sample size' is ambiguous. The benchmark measures checking, not extraction."
- **"How do you know it works?"** "20 automated tests, including the exact false alarms we hit on real papers; 20/20 on the planted benchmark (95% CI 0.84–1.00); and 9 flags across 341 numbers on unmodified papers, each shown with its recomputation."
- **"Cost?"** "About 3k to 30k tokens per paper, mostly on the cheapest model. Most of the checking needs no AI at all."
