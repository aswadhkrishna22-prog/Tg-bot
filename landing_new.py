def render_home_page(stady_css):
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#080b12">
<meta name="description" content="Adolf-StreamX: Share files from Telegram and watch them on your TV.">
<title>Adolf-StreamX | Stream Without Limits</title>
<style>
""" + stady_css + """
.landing-page {
    --bg: #080b12;
    --panel: #111722;
    --muted: #9aa7ba;
    --text: #f5f7fb;
    --accent: #8b7cff;
    --line: rgba(255,255,255,.09);
    color: var(--text);
    min-height: 100vh;
    background: var(--bg);
    font-family: Inter, system-ui, sans-serif;
}
.landing-page * { box-sizing: border-box; }
.landing-page a { color: inherit; text-decoration: none; }
.landing-page .wrap { width: min(1120px, calc(100% - 40px)); margin: auto; }
.landing-page .nav {
    display: flex; justify-content: space-between; align-items: center;
    padding: 24px 0; border-bottom: 1px solid var(--line);
}
.landing-page .logo { font-size: 19px; font-weight: 800; letter-spacing: -.5px; }
.landing-page .logo span { color: var(--accent); }
.landing-page .nav-link {
    color: #d9d6ff; font-size: 13px; font-weight: 700;
    padding: 11px 17px; border: 1px solid rgba(139,124,255,.35);
    border-radius: 999px;
}
.landing-page .hero {
    display: grid; grid-template-columns: 1.1fr .9fr; gap: 50px;
    align-items: center; padding: 90px 0 80px;
}
.landing-page .eyebrow {
    color: #aaa0ff; font-size: 12px; font-weight: 800;
    letter-spacing: 2px; text-transform: uppercase;
}
.landing-page h1 {
    font-size: clamp(42px, 6vw, 72px); line-height: 1.04;
    letter-spacing: -3px; margin: 18px 0;
}
.landing-page h1 span {
    background: linear-gradient(100deg, #b7adff, #8b7cff, #66d8ff);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
.landing-page .lead {
    max-width: 510px; color: var(--muted); font-size: 16px;
    line-height: 1.8; margin: 0 0 28px;
}
.landing-page .actions { display: flex; flex-wrap: wrap; gap: 12px; }
.landing-page .primary, .landing-page .secondary {
    display: inline-flex; justify-content: center; align-items: center;
    padding: 14px 20px; border-radius: 12px; font-size: 14px;
    font-weight: 800; transition: transform .2s ease;
}
.landing-page .primary {
    background: linear-gradient(110deg, #8b7cff, #6555df);
    color: white; box-shadow: 0 10px 35px rgba(113,94,255,.22);
}
.landing-page .secondary {
    border: 1px solid var(--line); background: rgba(255,255,255,.03);
}
.landing-page .primary:hover, .landing-page .secondary:hover { transform: translateY(-2px); }
.landing-page .visual {
    min-height: 330px; border: 1px solid var(--line); border-radius: 28px;
    padding: 22px; background:
      radial-gradient(ellipse at 80% 15%, rgba(119,103,255,.25), transparent 50%),
      linear-gradient(145deg, #171e2c, #0d111a);
    display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 25px 80px rgba(0,0,0,.28);
}
.landing-page .visual-top { display: flex; justify-content: space-between; align-items: center; }
.landing-page .online {
    display: inline-flex; align-items: center; gap: 8px;
    color: #a7f3c0; font-size: 11px; font-weight: 800;
    letter-spacing: 1px;
}
.landing-page .dot { width: 7px; height: 7px; border-radius: 50%; background: #50df91; box-shadow: 0 0 12px #50df91; }
.landing-page .screen {
    border: 1px solid rgba(255,255,255,.1); border-radius: 18px;
    background: rgba(5,8,14,.55); padding: 25px; text-align: center;
}
.landing-page .screen-icon { font-size: 52px; margin-bottom: 12px; }
.landing-page .screen-title { font-size: 17px; font-weight: 800; }
.landing-page .screen-sub { color: var(--muted); font-size: 12px; margin-top: 8px; }
.landing-page .visual-foot { color: #9ba8bb; font-size: 11px; text-align: center; }
.landing-page .section { padding: 45px 0 75px; }
.landing-page .section-head { text-align: center; margin-bottom: 32px; }
.landing-page h2 { font-size: clamp(26px, 4vw, 38px); letter-spacing: -1px; margin: 10px 0; }
.landing-page .section-head p { color: var(--muted); line-height: 1.7; }
.landing-page .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.landing-page .feature {
    padding: 25px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 18px;
}
.landing-page .feature-icon { font-size: 25px; }
.landing-page .feature h3 { font-size: 16px; margin: 18px 0 9px; }
.landing-page .feature p { color: var(--muted); font-size: 13px; line-height: 1.75; margin: 0; }

.landing-page .final-cta {
    padding: 35px 24px 75px;
    text-align: center;
}
.landing-page .cta-inner {
    max-width: 720px;
    margin: auto;
    padding: 48px 24px;
    border: 1px solid rgba(139,124,255,.22);
    border-radius: 24px;
    background: radial-gradient(ellipse at 50% 0%, rgba(139,124,255,.17), transparent 65%), #101521;
}
.landing-page .cta-inner h2 { margin: 12px 0; }
.landing-page .cta-inner p {
    color: var(--muted);
    line-height: 1.7;
    margin: 0 0 24px;
}
.landing-page .footer {
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    padding: 22px 0 28px;
    border-top: 1px solid var(--line);
    color: var(--muted);
    font-size: 12px;
}
.landing-page .footer a { color: #c4bcff; font-weight: 700; }
.landing-page .footer-note { opacity: .65; }

@media (max-width: 760px) {
    .landing-page .hero { grid-template-columns: 1fr; gap: 32px; padding: 60px 0; }
    .landing-page h1 { letter-spacing: -2px; }
    .landing-page .visual { min-height: 280px; }
    .landing-page .cards { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="landing-page">
<div class="wrap">
<header class="nav">
    <div class="logo">Adolf<span>·</span>StreamX</div>
    <a class="nav-link" href="/pair">Pair TV ↗</a>
</header>
<main>
<section class="hero">
    <div>
        <div class="eyebrow">Your files. Your screen.</div>
        <h1>From Telegram<br>to your <span>big screen.</span></h1>
        <p class="lead">Share a file through Telegram, open it on your phone, and continue watching on your TV. Simple streaming, without the usual hassle.</p>
        <div class="actions">
            <a class="primary" href="/pair">📺 Pair your TV</a>
            <a class="secondary" href="#how-it-works">How it works ↓</a>
        </div>
    </div>
    <div class="visual">
        <div class="visual-top">
            <div class="logo">Adolf<span>·</span>StreamX</div>
            <div class="online"><span class="dot"></span> SERVER ONLINE</div>
        </div>
        <div class="screen">
            <div class="screen-icon">▶</div>
            <div class="screen-title">Ready for your next stream</div>
            <div class="screen-sub">Connect your TV and enjoy.</div>
        </div>
        <div class="visual-foot">A smoother way to watch your shared files</div>
    </div>
</section>
<section class="section">
    <div class="section-head">
        <div class="eyebrow">Made for easy streaming</div>
        <h2>Everything in one place</h2>
        <p>From sharing to playback, the essentials are right where you need them.</p>
    </div>
    <div class="cards">
        <article class="feature">
            <div class="feature-icon">✈️</div>
            <h3>Telegram sharing</h3>
            <p>Send a video or file to the bot and get a share page to continue from your phone or TV.</p>
        </article>
        <article class="feature">
            <div class="feature-icon">📺</div>
            <h3>TV playback</h3>
            <p>Pair your TV with a code and open the receiver page without typing long links.</p>
        </article>
        <article class="feature">
            <div class="feature-icon">▶️</div>
            <h3>Player options</h3>
            <p>Choose the browser player or use supported external players such as VLC and MX Player.</p>
        </article>
    </div>
</section>
<section class="section" id="how-it-works">
    <div class="section-head">
        <div class="eyebrow">Three simple steps</div>
        <h2>Start watching in minutes</h2>
        <p>No complicated setup. Just share, pair, and play.</p>
    </div>
    <div class="cards">
        <article class="feature">
            <div class="feature-icon">01</div>
            <h3>Send your file</h3>
            <p>Send a video or file to the Adolf-StreamX Telegram bot.</p>
        </article>
        <article class="feature">
            <div class="feature-icon">02</div>
            <h3>Open the share page</h3>
            <p>Open the generated share page and find your TV pairing code.</p>
        </article>
        <article class="feature">
            <div class="feature-icon">03</div>
            <h3>Pair and play</h3>
            <p>Open this page on your TV, tap Pair TV, and enter your code.</p>
        </article>
    </div>
</section>
<section class="final-cta">
    <div class="cta-inner">
        <div class="eyebrow">Ready when you are</div>
        <h2>Your next stream is one tap away.</h2>
        <p>Connect your TV and enjoy your shared files on a bigger screen.</p>
        <a class="primary" href="/pair">📺 Pair your TV</a>
    </div>
</section>
</main>
<footer class="footer">
    <div>Made with <span class="heart">❤️</span> by
        <a href="https://www.instagram.com/2aswadhh_._kr"
           target="_blank" rel="noopener noreferrer">@aswadh_kr</a>
    </div>
    <div class="footer-note">Adolf-StreamX</div>
</footer>
</div>
</div>
</body>
</html>"""
