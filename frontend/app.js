const DATA_URL = "./wrapped_story_data.json";
const app = document.querySelector("#app");
const numberFormat = new Intl.NumberFormat("en-IN");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const count = (value) => Number.isFinite(Number(value)) ? numberFormat.format(Number(value)) : "—";
const safeNum = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;

function fullDate(iso) {
  if (!iso || typeof iso !== "string") return null;
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
}
function monthLabel(period) {
  const match = typeof period === "string" && period.match(/^(\d{4})-(\d{2})$/);
  if (!match) return null;
  const label = new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)));
  return label === "Sep" ? "Sept" : label;
}
function clockLabel(iso) {
  const match = typeof iso === "string" && iso.match(/T(\d{2}):(\d{2})/);
  if (!match) return null;
  const hour = Number(match[1]);
  return `${hour % 12 || 12}:${match[2]} ${hour < 12 ? "AM" : "PM"}`;
}
function compactClockRange(first, last) {
  if (!first || !last) return first || last || null;
  const a = first.match(/^(\d{1,2}):(\d{2}) (AM|PM)$/);
  const b = last.match(/^(\d{1,2}):(\d{2}) (AM|PM)$/);
  if (a && b && a[1] === b[1] && a[3] === b[3]) return `${a[1]}:${a[2]}–${b[2]} ${b[3]}`;
  return `${first}–${last}`;
}
function calendarLabel(isoDate) {
  if (typeof isoDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return null;
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, day)));
}
function durationLabel(seconds) {
  if (!Number.isFinite(Number(seconds))) return null;
  const totalMinutes = Math.floor(Number(seconds) / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}
function shortRange(range) {
  const first = fullDate(range?.first_local);
  const last = fullDate(range?.last_local);
  return first && last ? `${first} — ${last}` : null;
}
function timeLabel(seconds) {
  if (!Number.isFinite(Number(seconds))) return "—";
  const value = Number(seconds);
  if (value < 1) return "<1 sec";
  if (value < 60) return `${Math.round(value)} sec`;
  if (value < 3600) {
    const minutes = Math.floor(value / 60);
    const remainder = Math.round(value % 60);
    return remainder ? `${minutes}m ${remainder}s` : `${minutes} min`;
  }
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return minutes ? `${hours}h ${minutes}m` : `${hours} hr`;
}
function roleName(data, role) {
  return data.participants?.[role] || role || "Someone";
}
function countMarkup(value, className = "counter-value") {
  if (!Number.isFinite(Number(value))) return `<span class="${className}">—</span>`;
  return `<span class="${className}" data-count="${Number(value)}">0</span>`;
}
function commonPhrase(data) {
  const roles = Object.keys(data.participants_summary || {});
  if (roles.length !== 2) return null;
  const profiles = data.participants_summary;
  const left = [...(profiles[roles[0]]?.top_bigrams || []), ...(profiles[roles[0]]?.top_trigrams || [])];
  const rightMap = new Map([...(profiles[roles[1]]?.top_bigrams || []), ...(profiles[roles[1]]?.top_trigrams || [])].map((item) => [item.phrase, item.count]));
  const candidates = left.filter((item) => rightMap.has(item.phrase)).map((item) => ({
    phrase: item.phrase,
    leftCount: item.count,
    rightCount: rightMap.get(item.phrase),
    rank: Math.min(Number(item.count), Number(rightMap.get(item.phrase))),
  }));
  candidates.sort((a, b) => b.rank - a.rank);
  return candidates[0] || null;
}
function makeLanguage(data) {
  const roles = Object.keys(data.participants_summary || {});
  const profiles = data.participants_summary;
  const variants = ["haan haan", "ha ha"];
  const variantStats = roles.map((role, index) => {
    const item = (profiles[role]?.top_bigrams || []).find((entry) => entry.phrase?.toLocaleLowerCase("en") === variants[index]);
    const counter = item && Number.isFinite(Number(item.count))
      ? `<span class="lang-count" data-count="${Number(item.count)}">0</span>`
      : `<span class="lang-count">—</span>`;
    return `<div class="lang-variant"><span class="lang-variant-name">${escapeHTML(roleName(data, role))}</span><span class="lang-typing" aria-hidden="true"><i></i><i></i><i></i></span><strong class="lang-variant-word">${escapeHTML(item?.phrase || variants[index])}</strong><small>${counter} times</small></div>`;
  }).join("");
  const metrics = [
    { label: "Words per text", field: "average_words_per_message", format: (value) => Number.isFinite(value) ? value.toFixed(2) : "—" },
    { label: "Question messages", field: "question_messages", format: count },
    { label: "Double-text runs", field: "double_text_runs", format: count },
  ];
  const metricCards = metrics.map(({ label, field, format }) => {
    const values = roles.map((role) => ({ role, value: Number(profiles[role]?.[field]) }));
    const maximum = Math.max(0, ...values.map(({ value }) => Number.isFinite(value) ? value : 0));
    const bars = values.map(({ value }, index) => {
      const width = maximum > 0 && Number.isFinite(value) ? Math.max(0, value / maximum * 100) : 0;
      return `<span class="lang-habit-track ${index === 0 ? "habit-you" : "habit-her"}"><i style="--habit-width:${width}%"></i></span>`;
    }).join("");
    return `<article class="lang-habit"><div class="lang-habit-heading"><strong>${escapeHTML(label)}</strong><div class="lang-habit-values">${values.map(({ value }, index) => `<span class="${index === 0 ? "habit-you" : "habit-her"}">${escapeHTML(format(value))}</span>`).join("")}</div></div><div class="lang-habit-bars">${bars}</div></article>`;
  }).join("");
  return `<div class="language-floaters" aria-hidden="true"><span>haan</span><span>ha ha</span><span>haan haan</span><span>ha</span><span>haan</span></div>
    <section class="lang-card lang-spelling-card">
      <p class="language-kicker">Same thought, different spelling</p>
      <div class="lang-variants">${variantStats}</div>
      <p class="language-flirt">Two ways to say “haan haan.” Clearly, the conversation was going somewhere. 💌</p>
    </section>
    <section class="lang-card lang-habits-card">
      <p class="language-kicker">Your chat habits</p>
      <div class="lang-habit-legend">${roles.slice(0, 2).map((role, index) => `<span class="${index === 0 ? "habit-you" : "habit-her"}">${escapeHTML(roleName(data, role))}</span>`).join("")}</div>
      <div class="lang-habits">${metricCards}</div>
    </section>`;
}
function mediaItemCount(data, role, type) {
  const roleMedia = data.media?.by_role?.[role]?.attachment_item_counts || {};
  return roleMedia[type] || 0;
}
function chattyAwards(data) {
  const all = data.awards || {};
  const specs = [
    { key: "Reel Minister", icon: "🎬", value: (n) => `${count(n)} candidates`, compare: (other, otherName, data) => `vs ${otherName}: ${count(other)} · ${count(data.media?.reel_link_candidates?.total)} Reels combined`, note: "Reel-link candidates; linked content wasn't verified." },
    { key: "Flash Trophy", icon: "⚡", value: (n) => `${timeLabel(n)} avg`, compare: (other, otherName) => `${otherName}: ${timeLabel(other)} avg`, note: "Average valid reply delay across sender switches." },
    { key: "Yapper Medal", icon: "✍️", value: (n) => `${count(n)} characters`, compare: (other, otherName) => `${otherName}'s longest: ${count(other)} characters`, note: "Longest single text message." },
    { key: "Night Owl 2–5 AM", icon: "🌙", value: (n) => `${count(n)} messages`, compare: (other, otherName) => `${otherName}: ${count(other)} · 2–4:59 AM`, note: "Local time · reaction events excluded." },
    { key: "Simp of the Year", icon: "💘", value: (n) => `${count(n)} compliment phrase hits`, compare: (other, otherName) => `${otherName}: ${count(other)} phrase hits`, note: "Configured compliment keyword matches." },
  ];
  return specs.flatMap((spec, index) => {
    const record = all[spec.key];
    if (!record || record.status !== "winner" || !record.winner) return [];
    const winner = record.winner;
    const valueByRole = record.statistic_by_role || {};
    const otherRole = Object.keys(data.participants_summary || {}).find((role) => role !== winner);
    const value = Number(valueByRole[winner]);
    const otherValue = Number(valueByRole[otherRole]);
    if (!Number.isFinite(value) || !Number.isFinite(otherValue)) return [];
    const otherName = roleName(data, otherRole);
    return [{ ...spec, index, winner, name: roleName(data, winner), display: spec.value(value), compare: spec.compare(otherValue, otherName, data), note: spec.note }];
  });
}

function buildSlides(data) {
  const roles = Object.keys(data.participants_summary || {});
  const totalMessages = data.overview?.total_messages;
  const dateRange = shortRange(data.overview?.date_range);
  const slides = [];

  slides.push({
    id: "cover", theme: "cover", eyebrow: "A little time capsule", share: { label: "OUR CHAT WRAPPED 2026", stat: `${roleName(data, "you")} × ${roleName(data, "her")}` },
    content: `<div class="cover-main"><p class="eyebrow cover-eyebrow">A LITTLE TIME CAPSULE</p>
      <h1 class="cover-headline" aria-label="Two people. One chat."><span class="cover-line cover-line-solid" aria-hidden="true"><span class="cover-word" style="--word-index:0">Two</span> <span class="cover-word" style="--word-index:1">people.</span></span><span class="cover-line cover-line-outline" aria-hidden="true"><span class="cover-word" style="--word-index:2">One</span> <span class="cover-word" style="--word-index:3">chat.</span></span></h1>
      <p class="cover-copy">A wildly unreasonable number of messages. And somehow, still more to say.</p>
      <p class="cover-names">Abhishek <span aria-hidden="true">x</span> Prisha</p></div>`,
  });

  if (Number.isFinite(Number(totalMessages))) {
    const reelCandidates = data.media?.reel_link_candidates?.total;
    const busiestMonth = data.overview?.most_active_month?.[0];
    const instagramTime = data.time?.approximate_instagram_time || {};
    const instagramHours = instagramTime.rounded_hours !== null && instagramTime.rounded_hours !== undefined && Number.isFinite(Number(instagramTime.rounded_hours))
      ? `${count(instagramTime.rounded_hours)} hrs*`
      : "—";
    slides.push({
      id: "numbers", theme: "numbers", eyebrow: "The receipts are in", share: { label: "MESSAGES EXCHANGED", stat: count(totalMessages) },
      content: `<p class="eyebrow">The receipts are in</p><span class="hero-number is-counting">${countMarkup(totalMessages, "hero-counter")}</span><p class="hero-label">messages exchanged</p>
        <h2 class="section-heading numbers-punchline" aria-label="We could've written a book. Several, actually."><span class="punchline-line"><span>We could've written</span></span><span class="punchline-line"><span>a book.</span></span><span class="punchline-line outline"><span>Several, actually.</span></span></h2>
        <div class="overview-highlights">
          <article class="overview-highlight"><span class="overview-label">Reels exchanged</span><strong class="overview-value">${escapeHTML(count(reelCandidates))}</strong></article>
          <article class="overview-highlight"><span class="overview-label">Busiest month</span><strong class="overview-value">${escapeHTML(monthLabel(busiestMonth?.period) || "—")}</strong><span class="overview-detail">${escapeHTML(count(busiestMonth?.message_count))} messages</span></article>
          <article class="overview-highlight" aria-label="Rough estimate of Instagram time."><span class="overview-label">Approx. Instagram time</span><strong class="overview-value overview-value-estimate">${escapeHTML(instagramHours)}</strong></article>
        </div>
        ${dateRange ? `<span class="date-pill">${escapeHTML(dateRange)}</span>` : ""}
        <p class="estimate-footnote">* Rough estimate.</p>`,
    });
  }

  const starterPercent = { you: 63, her: 37 };
  const starterRoles = roles.slice(0, 2);
  const audioByRole = starterRoles.map((role) => ({ role, value: data.participants_summary?.[role]?.attachment_items?.audio_files }));
  const combinedAudioFiles = audioByRole.every((item) => item.value !== null && item.value !== undefined && Number.isFinite(Number(item.value)))
    ? audioByRole.reduce((total, item) => total + Number(item.value), 0)
    : null;
  const nightByRole = starterRoles.map((role) => ({ role, value: data.participants_summary?.[role]?.midnight_messages }));
  const combinedNightMessages = nightByRole.reduce((total, item) => total + safeNum(item.value), 0);
  const audioCardValues = audioByRole.map((item) => `<span class="plot-person-stat"><strong>${escapeHTML(count(item.value))}</strong><small>${escapeHTML(roleName(data, item.role))}</small></span>`).join("");
  const nightBreakdown = nightByRole.map((item) => `<span class="plot-night-person"><strong>${escapeHTML(count(item.value))}</strong><small>${escapeHTML(roleName(data, item.role))}</small></span>`).join("");
  slides.push({
    id: "conversation", theme: "chat", eyebrow: "Who keeps the plot moving?", share: { label: "WHO KEEPS THE PLOT MOVING?", stat: `${starterPercent.you}% × ${starterPercent.her}%` },
    content: `<p class="eyebrow">WHO KEEPS THE PLOT MOVING?</p>
      <h2 class="plot-headline" aria-label="It takes two to yap."><span class="plot-headline-word" style="--word-index:0">It</span> <span class="plot-headline-word" style="--word-index:1">takes</span> <span class="plot-headline-word" style="--word-index:2">two</span> <span class="plot-headline-word" style="--word-index:3">to</span> <span class="plot-headline-word" style="--word-index:4">yap.</span></h2>
      <p class="plot-support">But someone has to send the first message. 👀</p>
      <section class="starter-feature" aria-label="Conversation starter split: Abhishek 63 percent, Prisha 37 percent">
        <div class="starter-people">
          <div class="starter-person starter-you"><span class="starter-name">${escapeHTML(roleName(data, "you"))}</span><strong class="starter-percent"><span class="starter-counter" data-count="${starterPercent.you}">0</span>%</strong></div>
          <div class="starter-person starter-her"><span class="starter-name">${escapeHTML(roleName(data, "her"))}</span><strong class="starter-percent"><span class="starter-counter" data-count="${starterPercent.her}">0</span>%</strong></div>
        </div>
        <div class="starter-split" role="img" aria-label="63 percent Abhishek, 37 percent Prisha"><span class="split-you" style="--split:${starterPercent.you}%"></span><span class="split-her" style="--split:${starterPercent.her}%"></span></div>
      </section>
      <p class="plot-caption">Abhishek starts the plot. Prisha keeps it interesting. 👀</p>
      <div class="plot-mini-grid">
        <article class="plot-mini-card audio-mini"><div class="plot-card-title"><span aria-hidden="true">🎧</span><span>Audio attachments</span></div>
          <div class="plot-audio-highlight"><strong class="plot-audio-total">${escapeHTML(count(combinedAudioFiles))}</strong><span class="plot-audio-total-label">files in the chat</span><div class="plot-audio-wave" aria-hidden="true"><i style="--wave:34%"></i><i style="--wave:62%"></i><i style="--wave:82%"></i><i style="--wave:48%"></i><i style="--wave:100%"></i><i style="--wave:54%"></i><i style="--wave:76%"></i><i style="--wave:42%"></i><i style="--wave:66%"></i></div></div>
          <div class="plot-person-stats">${audioCardValues}</div>
          <p class="plot-mini-caption">The typing got a soundtrack.</p>
        </article>
        <article class="plot-mini-card night-mini"><div class="plot-card-title"><span aria-hidden="true">🌙</span><span>The night shift</span></div>
          <p class="plot-night-total">${escapeHTML(count(combinedNightMessages))}</p><p class="plot-time-range">messages · 12:00–4:59 AM</p>
          <div class="plot-night-breakdown">${nightBreakdown}</div>
          <p class="plot-mini-caption">Sleep was invited. Neither of us showed up.</p>
        </article>
      </div>`,
  });

  const hasLanguage = roles.some((role) => (data.participants_summary?.[role]?.top_bigrams || []).length || (data.participants_summary?.[role]?.top_meaningful_words || []).length);
  if (hasLanguage) slides.push({ id: "language", theme: "language", eyebrow: "A language of your own", share: { label: "OUR SHARED LANGUAGE", stat: commonPhrase(data)?.phrase || "Hinglish & heart" }, content: `<p class="eyebrow">A language of your own</p><h2 class="section-heading lang-headline" aria-label="Hinglish, shorthand & a few classics."><span class="lang-title-word" style="--word-index:0">Hinglish,</span> <span class="lang-title-word" style="--word-index:1">shorthand</span><br><span class="lang-title-word" style="--word-index:2">&amp;</span> <span class="lang-title-word" style="--word-index:3">a few</span> <span class="lang-title-word outline" style="--word-index:4">classics.</span></h2>${makeLanguage(data)}` });

  const emojiTop = data.emoji?.combined_top_10 || [];
  if (emojiTop.length) {
    const champion = emojiTop[0];
    const comparison = data.emoji?.comparison || {};
    const emojiWinner = comparison.more_diverse_emoji_vocabulary;
    const emojiPunchline = emojiWinner && emojiWinner !== "tie"
      ? `${escapeHTML(roleName(data, emojiWinner))} brought the bigger emoji vocabulary. The 😭 era was very real.`
      : "The 😭 era was very real.";
    slides.push({
      id: "emoji", theme: "emoji", eyebrow: "Emoji personalities", share: { label: "TOP EMOJI", stat: `${champion.emoji} · ${count(champion.count)}` },
      content: `<p class="eyebrow">Emoji personalities</p><h2 class="section-heading emoji-headline" aria-label="Full sentences were optional."><span class="emoji-title-word" style="--word-index:0">Full</span> <span class="emoji-title-word" style="--word-index:1">sentences</span><br><span class="emoji-title-word" style="--word-index:2">were</span> <span class="emoji-title-word outline" style="--word-index:3">optional.</span></h2>
        <div class="emoji-hero"><span class="emoji-hero-glyph">${escapeHTML(champion.emoji)}</span><div class="count-bubble"><strong>${countMarkup(champion.count, "emoji-champion-count")}</strong><span>uses</span></div></div>
        <div class="emoji-people">${roles.map((role) => {
          const profile = data.participants_summary?.[role] || {};
          const topEmojis = profile.top_emojis || [];
          const firstEmoji = topEmojis[0];
          return `<section class="emoji-person"><h3>${escapeHTML(roleName(data, role))}</h3><div class="emoji-row">${topEmojis.slice(0, 3).map((item, index) => `<span class="emoji-item" style="--emoji-index:${index}" title="${count(item.count)} uses">${escapeHTML(item.emoji)}</span>`).join("") || "—"}</div><p class="emoji-signature"><strong>${countMarkup(firstEmoji?.count, "emoji-signature-count")}×</strong><span>${escapeHTML(firstEmoji?.emoji || "")}</span></p></section>`;
        }).join("")}</div>
        <p class="emoji-punchline">${emojiPunchline}</p>`,
    });
  }

  const confession = data.confession_story || {};
  if (confession.status === "available") {
    const promptTime = clockLabel(confession.confession_prompt_at_local);
    const revealTime = clockLabel(confession.website_revealed_at_local);
    const surpriseTime = clockLabel(confession.website_surprise_at_local);
    const proposalTime = clockLabel(confession.proposal_link_sent_at_local);
    const girlfriendTime = clockLabel(confession.girlfriend_reply_at_local);
    const ilyTime = clockLabel(confession.first_i_love_you_back_at_local);
    const noSurpriseTime = clockLabel(confession.no_button_surprise_at_local);
    const lateTime = clockLabel(confession.late_night_last_message_at_local);
    const dateOne = calendarLabel(confession.relationship_date);
    const dateTwo = calendarLabel(confession.next_date);
    const dailyMessages = confession.messages_by_date || {};
    const twoDayTotal = Object.values(dailyMessages).reduce((sum, value) => sum + safeNum(value), 0);
    const dayOneNumber = Number(confession.relationship_date?.slice(-2));
    const dayTwoNumber = Number(confession.next_date?.slice(-2));
    const confessionEvents = [
      [girlfriendTime, "“I’m your girlfriend.”", "The answer arrived."],
      [ilyTime, "“I love you too.”", "And suddenly, officially us."],
      [noSurpriseTime, "You couldn’t believe she hadn’t pressed NO once.", "You told her you were literally so happy. 🥹"],
    ].filter(([time]) => time);
    const revealWindow = surpriseTime || compactClockRange(revealTime, surpriseTime);
    const promptEvent = promptTime ? [promptTime, "She asked you to say it again.", "Then came the plot twist. 💌", "" ] : null;
    const revealEvent = revealWindow ? [revealWindow, "You revealed the website was already ready.", surpriseTime ? "She was surprised you made it so quickly." : "The proposal page was built before the link arrived.", ""] : null;
    const confessionTimelineEvents = [
      promptEvent,
      revealEvent,
      proposalTime ? [proposalTime, "You sent the proposal site.", `A very ${roleName(data, "you")} way to ask. 💌`, ""] : null,
      ...confessionEvents.map(([time, headline, note]) => [time, headline, note, /girlfriend|love you/i.test(headline) ? "confession-event-pivotal" : ""]),
    ].filter(Boolean);
    slides.push({
      id: "confession", theme: "confession", eyebrow: "The night she said yes", share: { label: `SHE SAID YES · ${(dateOne || "CONFESSION DAY").toUpperCase()}`, stat: "One little website. One huge yes." },
      content: `<p class="eyebrow">${escapeHTML(dateOne ? `${dateOne} · the night she said yes` : "The night she said yes")}</p>
        <h2 class="section-heading confession-heading">One little website.<br><span class="outline">One enormous yes.</span></h2>
        <article class="confession-timeline" aria-label="The conversation as it unfolded">
          ${confessionTimelineEvents.map(([time, headline, note, className], index) => `<div class="confession-event ${className}" style="--event-index:${index}"><span class="confession-time">${escapeHTML(time)}</span><span class="confession-copy"><strong>${escapeHTML(headline)}</strong><small>${escapeHTML(note)}</small></span></div>`).join("")}
        </article>
        ${lateTime ? `<div class="confession-late"><strong>Still texting at ${escapeHTML(lateTime)}</strong><span>${escapeHTML(count(twoDayTotal))} messages across Sept ${escapeHTML(dayOneNumber || "")}–${escapeHTML(dayTwoNumber || "")}</span></div>` : ""}`,
    });
  }

  const awards = chattyAwards(data);
  if (awards.length) {
    const confettiGlyphs = ["😭", "💖", "✨", "💖", "😭", "✨", "💖", "✨", "😭", "💖", "✨", "😭", "💖", "✨"];
    const confetti = confettiGlyphs.map((glyph, index) => {
      const spread = ((index * 47) % 250) - 125;
      const rise = 145 + ((index * 37) % 115);
      const spin = (index % 2 ? 1 : -1) * (45 + index * 13);
      return `<span style="--burst-x:${spread}px;--burst-y:-${rise}px;--burst-spin:${spin}deg;--burst-delay:${(index % 7) * .035}s">${glyph}</span>`;
    }).join("");
    slides.push({
      id: "awards", theme: "awards", share: { label: "THE 2026 CHATTY AWARDS", stat: awards.map(({ name, key }) => `${key}: ${name}`).join(" · ") },
      content: `<div class="award-confetti" aria-hidden="true">${confetti}</div>
        <p class="eyebrow awards-eyebrow">The winners are in</p>
        <h2 class="section-heading awards-heading">The 2026<br><span class="outline">Chatty Awards.</span></h2>
        <div class="award-trophy" aria-hidden="true"><span>🏆</span><i></i></div>
        <section class="award-list" aria-label="Chat awards">
          ${awards.map(({ key, icon, name, display, compare, winner, index }) => `<article class="award-plaque ${winner === "you" ? "award-you" : winner === "her" ? "award-her" : ""}" style="--award-index:${index}">
            <span class="award-icon" aria-hidden="true">${icon}</span>
            <div class="award-copy"><span class="award-name">${escapeHTML(key)}</span><strong class="award-winner">${escapeHTML(name)}</strong><span class="award-result">${escapeHTML(display)}</span><small class="award-compare">${escapeHTML(compare)}</small></div>
          </article>`).join("")}
        </section>`,
    });
  }

  slides.push({
    id: "ending", theme: "ending", share: { label: "OUR STORY IS STILL BEING WRITTEN", stat: count(totalMessages) },
    content: `<div class="ending-floats" aria-hidden="true">
        <span class="ending-float ending-reel"><svg viewBox="0 0 48 48"><rect x="7" y="12" width="34" height="28" rx="7"/><path d="M7 20h34M13 12l6 8m5-8 6 8m5-8 6 8"/><path d="m21 25 10 6-10 6z"/></svg></span>
        <span class="ending-float ending-camera"><svg viewBox="0 0 48 48"><rect x="5" y="13" width="27" height="23" rx="6"/><path d="m32 20 11-6v21l-11-6z"/><circle cx="18.5" cy="24.5" r="5.5"/></svg></span>
        <span class="ending-float ending-whatsapp"><svg viewBox="0 0 48 48"><path d="M24 6a17 17 0 0 0-14.6 25.7L7 42l10.5-2.3A17 17 0 1 0 24 6Z"/><path d="M18 16c.7-.6 1.7-.4 2 .4l1.4 3c.3.7 0 1.3-.6 1.8l-1.1.9a13 13 0 0 0 5.8 5.8l.9-1.1c.5-.6 1.1-.9 1.8-.6l3 1.4c.8.3 1 1.3.4 2-1.2 1.5-3 2.1-4.9 1.7-6.2-1.3-11.1-6.2-12.4-12.4-.4-1.9.2-3.7 1.7-4.9Z"/></svg></span>
      </div>
      <span class="ending-heart" aria-hidden="true">❤️</span>
      <p class="eyebrow ending-eyebrow">Chapter one: Insta era complete.</p>
      <h2 class="ending-headline" aria-label="${count(totalMessages)} messages later... we outgrew the chatbox.">
        <span class="ending-count">${count(totalMessages)}</span>
        <span class="ending-message">messages later...</span>
        <span class="ending-evolution">we outgrew<br><span class="outline">the chatbox.</span></span>
      </h2>
      <p class="ending-note">From late-night IG texts to endless video calls, WhatsApp spam, and a lifetime of shared reels.</p>
      <p class="ending-footer">Same two people. A million more stories to come.</p>`,
  });
  return slides;
}

function formatCounter(el, onComplete, duration = 740) {
  const target = Number(el.dataset.count);
  if (!Number.isFinite(target)) return;
  if (reduceMotion) { el.textContent = numberFormat.format(target); onComplete?.(); return; }
  const start = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 4);
    el.textContent = numberFormat.format(Math.round(target * eased));
    if (progress < 1) requestAnimationFrame(tick);
    else {
      el.dispatchEvent(new CustomEvent("wrapped-counter-complete", { bubbles: true }));
      onComplete?.();
    }
  };
  requestAnimationFrame(tick);
}

function arrowIcon(direction) {
  return direction === "next"
    ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>`
    : `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>`;
}

function drawShareCard(slide, data) {
  const canvas = document.createElement("canvas");
  canvas.width = 1080; canvas.height = 1920;
  const ctx = canvas.getContext("2d");
  const palettes = {
    cover: ["#ec367f", "#253cc0"], numbers: ["#ffab55", "#6a1db4"], chat: ["#9b337f", "#351785"],
    night: ["#080d2a", "#5140a2"], language: ["#f05678", "#4832bd"], emoji: ["#ef397e", "#4732c3"],
    confession: ["#ef477f", "#532783"], love: ["#ea3d85", "#65318e"], awards: ["#301044", "#120d3b"], ending: ["#f07882", "#79358b"],
  };
  const [start, end] = palettes[slide.theme] || palettes.cover;
  const gradient = ctx.createLinearGradient(80, 80, 1000, 1840);
  gradient.addColorStop(0, start); gradient.addColorStop(1, end);
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(255,255,255,.11)";
  ctx.beginPath(); ctx.arc(880, 250, 260, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(160, 1660, 310, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.75)"; ctx.font = "800 30px system-ui"; ctx.letterSpacing = "6px";
  ctx.fillText("OUR CHAT WRAPPED 2026", 90, 140);
  ctx.letterSpacing = "0px";
  ctx.fillStyle = "#fff"; ctx.font = "1000 82px system-ui";
  const title = slide.share?.label || "A LITTLE STORY ABOUT US";
  wrapCanvasText(ctx, title.toUpperCase(), 90, 450, 900, 100);
  ctx.fillStyle = "rgba(255,255,255,.96)"; ctx.font = "950 112px system-ui";
  wrapCanvasText(ctx, String(slide.share?.stat || "A story in the making"), 90, 930, 900, 132);
  ctx.fillStyle = "rgba(255,255,255,.78)"; ctx.font = "600 34px system-ui";
  ctx.fillText(`${roleName(data, "you")}  ×  ${roleName(data, "her")}`, 90, 1740);
  ctx.fillStyle = "rgba(255,255,255,.6)"; ctx.font = "500 24px system-ui";
  ctx.fillText("Made from our chat stats · kept private", 90, 1800);
  canvas.toBlob((blob) => {
    if (!blob) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `our-chat-wrapped-${slide.id}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
  }, "image/png");
}
function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight) {
  const words = text.split(/\s+/); let line = "";
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, x, y); y += lineHeight; line = word;
    } else line = test;
  }
  if (line) ctx.fillText(line, x, y);
}

function render(data) {
  const slides = buildSlides(data);
  let index = 0;
  let touchStart = null;
  app.innerHTML = `<section class="story-stage" role="region" aria-label="Our Chat Wrapped story">
    <nav class="progress" aria-label="Story progress"></nav>
    <div class="story-topline"><span class="brand-mark">OUR CHAT WRAPPED · 2026</span><span class="slide-count"></span></div>
    <article class="story-content" tabindex="-1"></article>
    <footer class="story-footer"><button class="footer-button" data-action="prev" aria-label="Previous story">${arrowIcon("previous")}</button><div class="footer-middle"></div><button class="footer-button" data-action="next" aria-label="Next story">${arrowIcon("next")}</button></footer>
    <div class="toast" role="status"></div>
  </section>`;
  const stage = app.querySelector(".story-stage");
  const progress = app.querySelector(".progress");
  const content = app.querySelector(".story-content");
  const middle = app.querySelector(".footer-middle");
  const counter = app.querySelector(".slide-count");
  const brand = app.querySelector(".brand-mark");
  const prev = app.querySelector('[data-action="prev"]');
  const next = app.querySelector('[data-action="next"]');
  const toast = app.querySelector(".toast");
  let toastTimer;
  let coverExiting = false;
  let slideRevealTimer;

  function tell(message) {
    toast.textContent = message;
    toast.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-on"), 1700);
  }
  function paintProgress() {
    progress.innerHTML = slides.map((slide, position) => `<button class="progress-segment ${position < index ? "is-done" : position === index ? "is-current" : ""}" data-slide="${position}" aria-label="Go to story ${position + 1}: ${escapeHTML(slide.id)}"></button>`).join("");
  }
  function show() {
    clearTimeout(slideRevealTimer);
    const slide = slides[index];
    stage.className = `story-stage theme-${slide.theme}`;
    content.className = `story-content ${slide.id === "cover" ? "cover-content" : ""} ${slide.id === "ending" ? "ending-content" : ""} slide-enter`;
    content.innerHTML = slide.content;
    counter.textContent = `${String(index + 1).padStart(2, "0")} / ${String(slides.length).padStart(2, "0")}`;
    brand.textContent = slide.id === "cover" ? "OUR CHAT WRAPPED - 2026" : "OUR CHAT WRAPPED · 2026";
    if (slide.id === "cover") counter.textContent = `${String(index + 1).padStart(2, "0")}/${String(slides.length).padStart(2, "0")}`;
    prev.disabled = index === 0;
    next.disabled = index === slides.length - 1;
    middle.innerHTML = slide.id === "cover"
      ? `<button class="start-button" data-action="next">Let's go <span aria-hidden="true">→</span></button>`
      : slide.id === "ending"
        ? `<button class="replay-button" data-action="replay">Replay our story ↺</button>`
        : slide.share
          ? `<button class="save-card-button" data-action="save">Save this stat card ↗</button>`
          : `<span class="brand-mark">${String(index + 1).padStart(2, "0")} · ${slides.length}</span>`;
    paintProgress();
    content.classList.add("is-visible");
    const heroCounter = content.querySelector(".hero-counter");
    if (slide.id === "numbers" && heroCounter) {
      const hero = heroCounter.closest(".hero-number");
      const revealNumbers = () => {
        hero?.classList.remove("is-counting");
        hero?.classList.add("counter-finished");
        content.classList.add("numbers-revealed");
        setTimeout(() => content.classList.add("cards-revealed"), 1020);
      };
      if (reduceMotion) {
        heroCounter.textContent = numberFormat.format(Number(heroCounter.dataset.count));
        revealNumbers();
      } else {
        content.addEventListener("wrapped-counter-complete", (event) => {
          if (event.target === heroCounter) revealNumbers();
        }, { once: true });
      }
    }
    const starterCounters = [...content.querySelectorAll(".starter-counter")];
    let starterCountersComplete = 0;
    const starterBar = content.querySelector(".starter-split");
    let starterBarComplete = reduceMotion || !starterBar;
    const revealPlot = () => {
      if (starterCounters.length && starterCountersComplete === starterCounters.length && starterBarComplete) {
        content.classList.add("plot-revealed");
      }
    };
    if (starterCounters.length && starterBar && !reduceMotion) {
      starterBar.addEventListener("animationend", () => {
        starterBarComplete = true;
        revealPlot();
      }, { once: true });
    }
    const languageCounters = [...content.querySelectorAll(".lang-count[data-count]")];
    const startLanguageReveal = () => {
      content.classList.add("language-typed");
      languageCounters.forEach((el) => formatCounter(el, undefined, 520));
    };
    if (languageCounters.length) {
      if (reduceMotion) startLanguageReveal();
      else slideRevealTimer = setTimeout(startLanguageReveal, 920);
    }
    content.querySelectorAll("[data-count]").forEach((el) => {
      if (el.classList.contains("lang-count")) return;
      formatCounter(el, () => {
      if (!el.classList.contains("starter-counter")) return;
      starterCountersComplete += 1;
      revealPlot();
      });
    });
    document.title = `${slide.id === "cover" ? "Our Chat Wrapped" : slide.share?.label || "Our Chat Wrapped"} · 2026`;
  }
  function go(position) {
    index = Math.max(0, Math.min(slides.length - 1, position));
    show();
  }
  app.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action === "prev") go(index - 1);
    if (button.dataset.action === "next") {
      if (index === 0 && !coverExiting) {
        coverExiting = true;
        stage.classList.add("cover-exit");
        setTimeout(() => { coverExiting = false; go(1); }, 460);
      } else if (index !== 0) go(index + 1);
    }
    if (button.dataset.action === "replay") go(0);
    if (button.dataset.slide !== undefined) go(Number(button.dataset.slide));
    if (button.dataset.action === "save") {
      if (!slides[index].share) return;
      drawShareCard(slides[index], data);
      tell("Your stat card is ready ✨");
    }
  });
  window.addEventListener("keydown", (event) => {
    if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); go(index + 1); }
    if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); go(index - 1); }
    if (event.key === "Home") go(0);
    if (event.key === "End") go(slides.length - 1);
  });
  stage.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) { touchStart = null; return; }
    touchStart = { x: event.clientX, y: event.clientY };
  }, { passive: true });
  stage.addEventListener("pointerup", (event) => {
    if (!touchStart || event.target.closest("button")) return;
    const delta = event.clientX - touchStart.x;
    const vertical = Math.abs(event.clientY - touchStart.y);
    if (Math.abs(delta) > 48 && vertical < 80) go(index + (delta < 0 ? 1 : -1));
    touchStart = null;
  }, { passive: true });
  if (reduceMotion) document.documentElement.classList.add("reduced-motion");
  show();
}

async function boot() {
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(`Stats file returned ${response.status}`);
    const data = await response.json();
    if (data.privacy?.includes("No raw messages")) render(data);
    else throw new Error("The frontend stats file did not pass its privacy marker check.");
  } catch (error) {
    app.innerHTML = `<section class="error-card"><span class="loading-heart" aria-hidden="true">♥</span><h1>Your story is waiting</h1><p>Refresh the aggregate stats with <code>backend\\main.py</code>, then serve the <code>frontend</code> folder over localhost. No raw chat files are needed here.</p><p class="footnote">${escapeHTML(error.message)}</p></section>`;
  }
}

boot();
