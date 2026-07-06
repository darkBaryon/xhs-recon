/* 小红书风格本地站：渲染 window.FEED_DATA（web/feed.py 从 MySQL 全库装出）。
   纯原生 JS 无依赖，file:// 直接可开。头像/远程封面一律 no-referrer（xhs CDN 防盗链），
   加载失败回落为昵称首字彩圆 / 文字封面。*/
(function () {
  "use strict";

  const DATA = window.FEED_DATA || { notes: [], comments: [], accounts: [] };
  const $ = (s) => document.querySelector(s);
  const el = (t, c, txt) => {
    const e = document.createElement(t);
    if (c) e.className = c;
    if (txt !== undefined) e.textContent = txt;
    return e;
  };

  // 评论按笔记分组 + 楼中楼（一级按时间，子评论挂父楼后面）
  const cmtsByNote = new Map();
  for (const c of DATA.comments) {
    if (!cmtsByNote.has(c.nid)) cmtsByNote.set(c.nid, []);
    cmtsByNote.get(c.nid).push(c);
  }

  const fmtN = (n) => (n >= 10000 ? (n / 10000).toFixed(1) + "万" : String(n));
  const AVA_HUES = [355, 25, 95, 150, 205, 260, 310];
  const hue = (name) => {
    let h = 0;
    for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
    return AVA_HUES[h % AVA_HUES.length];
  };

  function avatar(url, name, px) {
    const fb = el("div", "ava ava-fb", (name || "?").slice(0, 1));
    fb.style.cssText = `width:${px}px;height:${px}px;background:hsl(${hue(name)},55%,60%);font-size:${Math.round(px * 0.42)}px`;
    if (!url) return fb;
    const img = el("img", "ava");
    img.referrerPolicy = "no-referrer";
    img.loading = "lazy";
    img.src = url;
    img.onerror = () => img.replaceWith(fb);
    return img;
  }

  /* ── 瀑布流 ── */
  const state = { q: "", sort: "date", acc: "" };

  function visibleNotes() {
    let notes = DATA.notes;
    if (state.acc) notes = notes.filter((n) => n.aid === state.acc);
    if (state.q) {
      const q = state.q.toLowerCase();
      notes = notes.filter((n) =>
        (n.title + "\n" + n.body + "\n" + n.tags.join(" ") + "\n" + n.author)
          .toLowerCase()
          .includes(q)
      );
    }
    const key = state.sort;
    notes = notes.slice();
    if (key === "date") notes.sort((a, b) => (b.date > a.date ? 1 : -1));
    else notes.sort((a, b) => b[key] - a[key]);
    return notes;
  }

  function card(note) {
    const c = el("div", "card");
    const cover = el("div", "cover");
    const src = note.imgs[0] || note.cover_remote;
    if (src) {
      const img = el("img");
      img.loading = "lazy";
      if (!note.imgs[0]) img.referrerPolicy = "no-referrer";
      img.src = src;
      img.onerror = () => {
        cover.replaceChildren(el("div", "t", note.title || note.body.slice(0, 60)));
        cover.classList.add("textonly");
      };
      cover.appendChild(img);
      if (note.video) cover.appendChild(el("div", "play", "▶"));
    } else {
      cover.classList.add("textonly");
      cover.appendChild(el("div", "t", note.title || note.body.slice(0, 60)));
    }
    c.appendChild(cover);
    // 文字封面已含标题，不再重复
    if (note.title && !cover.classList.contains("textonly")) {
      c.appendChild(el("div", "title", note.title));
    }
    const meta = el("div", "meta");
    meta.appendChild(avatar(note.avatar, note.author, 20));
    meta.appendChild(el("span", "nick", note.author));
    meta.appendChild(el("span", "like", "♡ " + fmtN(note.like)));
    c.appendChild(meta);
    c.onclick = () => openNote(note);
    return c;
  }

  function renderFeed() {
    const notes = visibleNotes();
    const feed = $("#feed");
    feed.replaceChildren(...notes.map(card));
    const nc = DATA.comments.length;
    $("#stats").textContent = `${notes.length}/${DATA.notes.length} 篇 · ${nc} 评论 · ${DATA.accounts.length} 账号`;
  }

  /* ── 侧栏账号 ── */
  function renderSidebar() {
    const list = $("#account-list");
    for (const a of DATA.accounts) {
      const item = el("div", "nav-item acct");
      item.appendChild(avatar(a.avatar, a.nick, 24));
      const nick = el("span", "nick", a.nick);
      if (a.fans) nick.title = `粉丝 ${fmtN(a.fans)}${a.descr ? "\n" + a.descr : ""}`;
      item.appendChild(nick);
      item.appendChild(el("span", "n", String(a.notes)));
      item.onclick = () => {
        state.acc = state.acc === a.aid ? "" : a.aid;
        document.querySelectorAll(".nav-item").forEach((e) => e.classList.remove("active"));
        (state.acc ? item : $("#nav-all")).classList.add("active");
        renderFeed();
        window.scrollTo(0, 0);
      };
      list.appendChild(item);
    }
    $("#nav-all").onclick = () => {
      state.acc = "";
      document.querySelectorAll(".nav-item").forEach((e) => e.classList.remove("active"));
      $("#nav-all").classList.add("active");
      renderFeed();
      window.scrollTo(0, 0);
    };
  }

  /* ── 笔记详情 ── */
  let galleryIdx = 0;

  function gallery(note) {
    const g = el("div", "gallery");
    const imgs = note.imgs;
    if (!imgs.length) {
      g.appendChild(el("div", "empty", note.video ? "视频未存本地（默认只存图）" : "无图片"));
      return g;
    }
    const img = el("img");
    img.src = imgs[galleryIdx];
    g.appendChild(img);
    if (imgs.length > 1) {
      const dots = el("div", "dots");
      imgs.forEach((_, i) => dots.appendChild(el("i", i === galleryIdx ? "on" : "")));
      const show = (i) => {
        galleryIdx = (i + imgs.length) % imgs.length;
        img.src = imgs[galleryIdx];
        [...dots.children].forEach((d, j) => d.classList.toggle("on", j === galleryIdx));
      };
      const prev = el("button", "nav prev", "‹");
      const next = el("button", "nav next", "›");
      prev.onclick = () => show(galleryIdx - 1);
      next.onclick = () => show(galleryIdx + 1);
      g.append(prev, next, dots);
    }
    return g;
  }

  function commentRow(c, isSub) {
    const row = el("div", "cmt" + (isSub ? " sub" : ""));
    row.appendChild(avatar(c.avatar, c.author, isSub ? 24 : 32));
    const main = el("div");
    main.appendChild(el("div", "who", c.author));
    main.appendChild(el("div", "txt", c.body));
    main.appendChild(el("div", "sub-meta", [c.date, c.ip].filter(Boolean).join(" · ")));
    row.appendChild(main);
    if (c.like) row.appendChild(el("span", "lk", "♡" + fmtN(c.like)));
    return row;
  }

  function openNote(note) {
    galleryIdx = 0;
    const box = $("#note-card");
    box.replaceChildren();

    const close = el("button", "close", "✕");
    close.onclick = closeNote;
    box.appendChild(close);
    box.appendChild(gallery(note));

    const pane = el("div", "pane");
    const head = el("div", "pane-head");
    head.appendChild(avatar(note.avatar, note.author, 40));
    const who = el("div");
    who.appendChild(el("div", "nick", note.author));
    who.appendChild(el("div", "sub", [note.date, note.ip].filter(Boolean).join(" · ")));
    head.appendChild(who);
    if (note.url) {
      const a = el("a", "open", "去小红书");
      a.href = note.url;
      a.target = "_blank";
      a.rel = "noreferrer";
      head.appendChild(a);
    }
    pane.appendChild(head);

    const body = el("div", "pane-body");
    if (note.title) body.appendChild(el("div", "n-title", note.title));
    body.appendChild(el("div", "n-text", note.body));
    if (note.tags.length) {
      const tags = el("div", "n-tags");
      note.tags.forEach((t) => tags.appendChild(el("span", "", "#" + t)));
      body.appendChild(tags);
    }
    body.appendChild(el("div", "n-date", note.date));
    const eng = el("div", "engage");
    eng.appendChild(el("span", "", "❤️ " + fmtN(note.like)));
    eng.appendChild(el("span", "", "⭐ " + fmtN(note.collect)));
    eng.appendChild(el("span", "", "💬 " + fmtN(note.comment)));
    body.appendChild(eng);

    // 楼中楼：一级楼保序，子评论跟在父楼后
    const cmts = cmtsByNote.get(note.id) || [];
    const roots = cmts.filter((c) => !c.parent);
    const subsByParent = new Map();
    for (const c of cmts) {
      if (!c.parent) continue;
      if (!subsByParent.has(c.parent)) subsByParent.set(c.parent, []);
      subsByParent.get(c.parent).push(c);
    }
    body.appendChild(
      el("div", "c-head", cmts.length ? `共 ${cmts.length} 条评论（已采样）` : "")
    );
    if (!cmts.length) body.appendChild(el("div", "c-none", "未采集到评论"));
    for (const c of roots) {
      body.appendChild(commentRow(c, false));
      for (const s of subsByParent.get(c.id) || []) body.appendChild(commentRow(s, true));
    }
    // 父楼不在采样内的孤儿子评论也别丢
    const rootIds = new Set(roots.map((c) => c.id));
    for (const c of cmts) {
      if (c.parent && !rootIds.has(c.parent)) body.appendChild(commentRow(c, true));
    }

    pane.appendChild(body);
    box.appendChild(pane);
    $("#modal").classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeNote() {
    $("#modal").classList.add("hidden");
    document.body.style.overflow = "";
  }

  /* ── 事件 ── */
  $("#search").addEventListener("input", (e) => {
    state.q = e.target.value.trim();
    renderFeed();
  });
  $("#sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    renderFeed();
  });
  document.querySelector(".modal-backdrop").onclick = closeNote;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeNote();
    if ($("#modal").classList.contains("hidden")) return;
    if (e.key === "ArrowLeft") document.querySelector(".gallery .prev")?.click();
    if (e.key === "ArrowRight") document.querySelector(".gallery .next")?.click();
  });

  renderSidebar();
  renderFeed();
})();
