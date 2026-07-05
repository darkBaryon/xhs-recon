/* 渲染 window.DATA（由生成时注入的 data.js 提供）成账号视图 / 选题流。
   纯原生 JS，无依赖；file:// 直接可开。数据拼装在 web/report.py 的 assemble()。*/
(function () {
  "use strict";

  const DATA = window.DATA;
  const $ = (s) => document.querySelector(s);
  const el = (t, c, txt) => {
    const e = document.createElement(t);
    if (c) e.className = c;
    if (txt != null) e.textContent = txt;
    return e;
  };

  if (!DATA) {
    document.body.innerHTML =
      '<div style="max-width:640px;margin:80px auto;font-family:sans-serif;color:#73767e">' +
      "未找到运行数据（data.js）。请先跑 <code>cli report</code> 生成快照。</div>";
    return;
  }

  let view = "acc";

  const fmtNum = (n) => {
    if (n == null) return null;
    return n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "万" : String(n);
  };
  const fmtDate = (iso) => (iso || "").replace(/^\d{4}-/, "").replace("-", "/");
  const VF = { 2: ["机构认证", "b-org"], 1: ["个人认证", "b-person"], 0: ["未认证", "b-none"] };
  const srcLabel = (s) => (s === "manual" ? "手动关注" : s === "auto" ? "榜单自动" : "搜索发现");

  function engEl(p) {
    const e = el("span", "eng");
    [["赞", p.like], ["藏", p.collect], ["评", p.comment]].forEach(([lab, v]) => {
      const s = el("span");
      s.append(lab + " ", el("b", v ? "" : "zero", fmtNum(v)));
      e.append(s);
    });
    return e;
  }

  function tagsEl(tags) {
    if (!tags || !tags.length) return null;
    const w = el("div", "ptags");
    tags.forEach((t) => w.append(el("span", "ptag", "#" + t)));
    return w;
  }

  function accCard(a, i) {
    const c = el("div", "card" + (a.verify_type === 2 ? " vf" : ""));
    const head = el("div", "chead");
    head.append(el("div", "name", a.nickname), el("div", "rank", "#" + (i + 1)));
    c.append(head);

    const bd = el("div", "badges");
    if (DATA.tracked || a.has_profile) {
      if (!a.has_profile) {
        bd.append(el("span", "badge b-noprof", "档案未采集"));
      } else {
        const [t, cl] = VF[a.verify_type] || ["认证未知", "b-none"];
        bd.append(el("span", "badge " + cl, t));
      }
    }
    bd.append(el("span", "badge b-src", srcLabel(a.source)));
    c.append(bd);

    if (a.has_profile) {
      const id = el("div", "idrow");
      const add = (lab, val) => {
        const s = el("span");
        s.append(lab + " ", el("b", "", val));
        id.append(s);
      };
      add("粉丝", fmtNum(a.fans));
      add("关注", fmtNum(a.follows));
      if (a.ip_location) add("IP", a.ip_location);
      if (a.red_id) add("小红书号", a.red_id);
      c.append(id);
    } else if (a.has_rank) {
      const id = el("div", "idrow");
      const add = (lab, val) => {
        const s = el("span");
        s.append(lab + " ", el("b", "", val));
        id.append(s);
      };
      add("相关笔记", a.relevant_note_count);
      add("关键词命中", a.keyword_hit_count);
      add("均互动", Math.round(a.avg_interaction));
      c.append(id);
    } else if (DATA.tracked) {
      const id = el("div", "idrow");
      id.append(el("span", "na", "主页档案本次未落盘（有笔记、无认证信息）"));
      c.append(id);
    }

    const pf = el("div", "prof");
    const top = el("div", "prof-top");
    let scoreVal, scoreMax, label, subs = [];
    if (a.has_pf) {
      scoreVal = a.profile_score;
      scoreMax = 16;
      label = "专业度评分";
      subs = [["垂直度", Math.round(a.vertical_ratio * 100) + "%"], ["窗内发帖", a.recent_note_count + " 篇"]];
    } else if (a.has_rank) {
      scoreVal = a.account_score;
      scoreMax = DATA.max_score;
      label = "搜索评分";
      subs = [["相关笔记", a.relevant_note_count + " 篇"]];
    }
    if (scoreVal != null) {
      top.append(el("span", "", label), el("span", "score", scoreVal.toFixed(2)));
      pf.append(top);
      const m = el("div", "meter");
      const bar = el("i");
      bar.style.width = Math.min(100, (scoreVal / scoreMax) * 100) + "%";
      m.append(bar);
      pf.append(m);
      if (subs.length) {
        const sb = el("div", "prof-sub");
        subs.forEach(([l, v]) => {
          const s = el("span");
          s.append(l + " ", el("b", "", v));
          sb.append(s);
        });
        pf.append(sb);
      }
      c.append(pf);
    }

    const ps = el("div", "posts");
    ps.append(el("div", "posts-h", (DATA.window_feed ? "窗内笔记 · " : "搜索命中 · ") + a.notes.length + " 篇（按互动排序）"));
    if (!a.notes.length) {
      ps.append(el("div", "empty", "无笔记"));
    } else {
      const list = el("div", "plist");
      a.notes.forEach((p) => {
        const item = el("div", "post");
        const link = el("a", "", p.title || "（无标题）");
        link.href = p.url;
        link.target = "_blank";
        link.rel = "noopener";
        item.append(link);
        const mt = el("div", "pmeta");
        if (p.date) mt.append(el("span", "d", fmtDate(p.date)));
        mt.append(engEl(p));
        item.append(mt);
        const tg = tagsEl(p.tags);
        if (tg) item.append(tg);
        list.append(item);
      });
      ps.append(list);
    }
    c.append(ps);
    return c;
  }

  function feedRow(p, i) {
    const r = el("div", "frow");
    r.append(el("div", "fr-rank", String(i + 1)));
    const main = el("div", "fr-main");
    const link = el("a", "", p.title || "（无标题）");
    link.href = p.url;
    link.target = "_blank";
    link.rel = "noopener";
    main.append(link);
    const sub = el("div", "fr-sub");
    if (p.nickname) sub.append(el("span", "who", p.nickname));
    if (p.date) sub.append(el("span", "d", fmtDate(p.date)));
    (p.tags || []).slice(0, 3).forEach((t) => sub.append(el("span", null, "#" + t)));
    main.append(sub);
    r.append(main);
    const e = el("div", "fr-eng");
    e.append(el("b", null, fmtNum(p.eng)), document.createTextNode(" "), el("span", "lab", "总互动"));
    r.append(e);
    return r;
  }

  function render() {
    const canVf = DATA.summary.verified > 0;
    const vfonly = canVf && $("#vfonly").checked;

    const grid = $("#grid");
    grid.textContent = "";
    const accs = DATA.accounts.filter((a) => !vfonly || a.verify_type === 2);
    accs.forEach((a, i) => grid.append(accCard(a, i)));

    const fl = $("#feedlist");
    fl.textContent = "";
    const vfSet = new Set(DATA.accounts.filter((a) => a.verify_type === 2).map((a) => a.nickname));
    const fd = DATA.feed.filter((p) => !vfonly || vfSet.has(p.nickname));
    fd.forEach((p, i) => fl.append(feedRow(p, i)));

    $("#count").textContent = view === "acc" ? accs.length + " 个账号" : fd.length + " 条笔记";
  }

  function show(v) {
    view = v;
    $("#tab-acc").setAttribute("aria-selected", v === "acc");
    $("#tab-feed").setAttribute("aria-selected", v === "feed");
    $("#view-acc").classList.toggle("hidden", v !== "acc");
    $("#view-feed").classList.toggle("hidden", v !== "feed");
    render();
  }

  function init() {
    const s = DATA.summary;
    $("#title").append(DATA.tracked ? "关注账号情报" : "搜索账号榜单");
    $("#title").append(el("span", "sub", DATA.window_feed ? " creator 主页 · 窗内发帖" : " 搜索命中 · 全量笔记"));

    let when = "—";
    if (DATA.collected_at) {
      const d = new Date(DATA.collected_at);
      if (!isNaN(d)) {
        const p = (n) => String(n).padStart(2, "0");
        when = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
      }
    }
    const rm = $("#runmeta");
    const seg = (l, v) => {
      const x = el("span");
      x.append(l + " ", el("b", "", v));
      return x;
    };
    rm.append(seg("采集", when), seg("时间窗", DATA.window_feed ? "近 30 天" : "全量"), seg("快照目录", DATA.run_dir));

    const tiles = [
      [s.accounts, DATA.tracked ? "关注账号" : "搜索账号", ""],
      [s.notes, DATA.window_feed ? "窗内笔记" : "搜索笔记", ""],
      [s.profiles, "主页档案", "／ " + s.accounts + " 账号"],
      [s.verified, "机构认证", "verify_type=2", true],
    ];
    const tw = $("#tiles");
    tiles.forEach(([n, l, sub, hot]) => {
      const t = el("div", "tile");
      t.append(el("div", "n" + (hot ? " hot" : ""), String(n)));
      const ll = el("div", "l");
      ll.append(document.createTextNode(l + " "));
      if (sub) ll.append(el("em", "", sub));
      t.append(ll);
      tw.append(t);
    });
    if (!s.verified) $("#vfwrap").classList.add("hidden");

    $("#foot").innerHTML =
      "数据来自 <code>" + DATA.run_dir + "/</code> 的导出 · 专业度 = 垂直度×10 + 窗内发帖数 · " +
      "互动 0 多为 creator 主页未采集互动、非真实 0 · 点标题跳小红书原帖 · 由 <code>cli report</code> 生成";

    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.view)));
    $("#vfonly").addEventListener("change", render);
    render();
  }

  init();
})();
