/*
 * 我的關注（自訂選單）
 * ====================
 * 選單先存在「這個瀏覽器」的 localStorage 裡（GitHub Pages 是靜態網頁，沒有伺服器可以存）。
 * 開啟「雲端同步」後，會另外存一份到使用者自己 GitHub 帳號下的私密 Gist，
 * 每台裝置貼一次只有 gist 權限的權杖，手機、電腦就會自動同步（見下方「雲端同步」）。
 * 沒開同步時也可以用「匯出 / 匯入」手動搬移或備份。
 *
 * 報表頁（波段、當沖）：每張卡片右上角加一顆「☆ 關注」按鈕，點開選要加進哪個選單。
 * 關注頁（watchlist.html）：切換選單、改名、新增/刪除選單（最多 MAX_LISTS 個）、輸入代號加入、移除。
 */
(function () {
  "use strict";

  var STORAGE_KEY = "stock-screener-watchlists-v1";
  var MAX_LISTS = 5;
  var MAX_NAME_LEN = 20;

  // ---------------- 儲存 ----------------
  // 資料只有 { lists, updatedAt }；「目前在看哪個選單」是每台裝置自己的，另外存，不參與同步。
  var CURRENT_KEY = "stock-screener-watchlists-current-v1";
  var memoryFallback = null; // localStorage 不能用（無痕模式等）時，至少本頁操作還能用

  function defaultState() {
    return { lists: [{ id: newId(), name: "我的關注", codes: [] }], updatedAt: 0 };
  }

  function newId() {
    return "l" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  function sanitize(state) {
    if (!state || !Array.isArray(state.lists)) return defaultState();
    var lists = state.lists
      .filter(function (l) { return l && typeof l.name === "string" && Array.isArray(l.codes); })
      .slice(0, MAX_LISTS)
      .map(function (l) {
        var seen = {};
        return {
          id: typeof l.id === "string" ? l.id : newId(),
          name: l.name.slice(0, MAX_NAME_LEN) || "未命名",
          codes: l.codes.map(String).filter(function (c) {
            if (!c || seen[c]) return false;
            seen[c] = true;
            return true;
          }),
        };
      });
    if (!lists.length) return defaultState();
    return { lists: lists, updatedAt: typeof state.updatedAt === "number" ? state.updatedAt : 0 };
  }

  function load() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) return sanitize(JSON.parse(raw));
    } catch (e) { /* 讀不到就用預設 */ }
    if (!memoryFallback) {
      // 第一次使用：建立預設選單並馬上存起來，選單 id 才會固定（不然每次讀都是新的 id）
      writeLocal(defaultState());
    }
    return sanitize(memoryFallback);
  }

  function writeLocal(state) {
    memoryFallback = state;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) { /* 寫不進去時只保留在本頁記憶體 */ }
  }

  // 使用者改了選單內容：記下修改時間、存本機，有開同步就排程上傳
  function save(state) {
    state.updatedAt = Date.now();
    writeLocal(state);
    Sync.schedule();
  }

  function getCurrent() {
    try { return window.localStorage.getItem(CURRENT_KEY); } catch (e) { return null; }
  }

  function setCurrent(id) {
    try {
      if (id) window.localStorage.setItem(CURRENT_KEY, id); else window.localStorage.removeItem(CURRENT_KEY);
    } catch (e) { /* 只是記住分頁，失敗沒關係 */ }
  }

  function listsContaining(state, code) {
    return state.lists.filter(function (l) { return l.codes.indexOf(code) >= 0; });
  }

  function toggleCode(state, listId, code) {
    state.lists.forEach(function (l) {
      if (l.id !== listId) return;
      var i = l.codes.indexOf(code);
      if (i >= 0) l.codes.splice(i, 1); else l.codes.push(code);
    });
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // ---------------- 雲端同步（GitHub 私密 Gist）----------------
  // 每台裝置貼一次「只有 gist 權限」的 GitHub 權杖，選單會存到使用者自己帳號下的一個私密 Gist：
  //   - 本機有修改 → 0.8 秒後上傳
  //   - 打開頁面 / 切回這個分頁 → 下載最新版
  //   - 兩台裝置都在上次同步後改過（例如一台離線時改）→ 兩邊合併（同名選單的股票取聯集），
  //     「加入的」不會不見；只是在另一台同時刪掉的股票可能會回來，要再刪一次。
  var Sync = (function () {
    var SYNC_KEY = "stock-screener-sync-v1";
    var GIST_FILE = "stock-screener-watchlists.json";
    var API = "https://api.github.com";
    var TOKEN_URL = "https://github.com/settings/tokens/new?scopes=gist&description=" +
      encodeURIComponent("stock-screener 我的關注同步");

    var timer = null;
    var chain = Promise.resolve();
    var listeners = [];
    var status = { state: "off", msg: "", at: null };

    function cfg() {
      try { return JSON.parse(window.localStorage.getItem(SYNC_KEY)) || null; } catch (e) { return null; }
    }

    function setCfg(c) {
      try {
        if (c) window.localStorage.setItem(SYNC_KEY, JSON.stringify(c));
        else window.localStorage.removeItem(SYNC_KEY);
      } catch (e) { /* 存不了就只在本頁有效 */ }
    }

    function setStatus(state, msg) {
      status = { state: state, msg: msg || "", at: state === "ok" ? new Date() : status.at };
      listeners.forEach(function (fn) { fn(status); });
    }

    function errMsg(e) {
      if (e && e.status === 401) return "權杖無效或已過期，請中斷後重新連線";
      if (e && (e.status === 403 || e.status === 404)) return "權杖沒有 gist 權限、雲端選單被刪除，或 GitHub 暫時限流";
      if (e && e.status) return "GitHub 回應錯誤（" + e.status + "）";
      return "連不上 GitHub，網路恢復後會再同步";
    }

    function gh(method, path, token, body, keepalive) {
      var headers = {
        Authorization: "Bearer " + token,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      };
      if (body) headers["Content-Type"] = "application/json";
      return fetch(API + path, {
        method: method, headers: headers, cache: "no-store", keepalive: !!keepalive,
        body: body ? JSON.stringify(body) : undefined,
      }).then(function (r) {
        if (!r.ok) { var e = new Error("HTTP " + r.status); e.status = r.status; throw e; }
        return r.status === 204 ? null : r.json();
      });
    }

    function payload(state) {
      return JSON.stringify({ version: 1, updatedAt: state.updatedAt, lists: state.lists }, null, 1);
    }

    function remoteFrom(gist) {
      var f = gist && gist.files && gist.files[GIST_FILE];
      if (!f || typeof f.content !== "string") return null;
      try { return sanitize(JSON.parse(f.content)); } catch (e) { return null; }
    }

    function isEmpty(state) {
      return state.lists.every(function (l) { return !l.codes.length; });
    }

    // 兩邊都改過時合併：以雲端為底，本機同名選單的股票併進去，本機多出來的選單接在後面（最多 MAX_LISTS 個）
    function merge(local, remote) {
      var out = remote.lists.map(function (l) { return { id: l.id, name: l.name, codes: l.codes.slice() }; });
      local.lists.forEach(function (l) {
        var same = out.filter(function (o) { return o.name === l.name; })[0];
        if (!same && !l.codes.length) return; // 本機空的選單不用帶過去
        if (!same && out.length < MAX_LISTS) {
          out.push({ id: l.id, name: l.name, codes: l.codes.slice() });
          return;
        }
        var target = same || out[out.length - 1];
        l.codes.forEach(function (c) { if (target.codes.indexOf(c) < 0) target.codes.push(c); });
      });
      return { lists: out, updatedAt: Date.now() };
    }

    function push(c, state, keepalive) {
      var files = {};
      files[GIST_FILE] = { content: payload(state) };
      return gh("PATCH", "/gists/" + c.gistId, c.token, { files: files }, keepalive);
    }

    // 同步一次：比較「上次同步看到的版本」(seenAt) 決定要下載、上傳還是合併。回傳本機資料有沒有被改。
    function reconcile(keepalive) {
      var c = cfg();
      if (!c) return Promise.resolve(false);
      setStatus("syncing", "同步中…");
      var local = load();
      return gh("GET", "/gists/" + c.gistId, c.token).then(function (gist) {
        var remote = remoteFrom(gist);
        var seen = c.seenAt || 0;
        var localDirty = local.updatedAt > seen;
        var remoteChanged = !!remote && remote.updatedAt > seen;
        var result = local, needPush = false, changedLocal = false;
        if (!remote) { needPush = true; }
        else if (localDirty && remoteChanged) { result = merge(local, remote); needPush = changedLocal = true; }
        else if (remoteChanged) { result = remote; changedLocal = true; }
        else if (localDirty) { needPush = true; }
        if (changedLocal) writeLocal(result);
        return (needPush ? push(c, result, keepalive) : Promise.resolve()).then(function () {
          var c2 = cfg();
          if (c2 && c2.gistId === c.gistId) { c2.seenAt = result.updatedAt; setCfg(c2); }
          setStatus("ok");
          return changedLocal;
        });
      }).catch(function (e) {
        setStatus("error", errMsg(e));
        return false;
      });
    }

    function run(keepalive) {
      chain = chain.then(function () { return reconcile(keepalive); });
      return chain;
    }

    // 找使用者帳號下有沒有之前建好的同步 Gist（換新裝置時用同一個）
    function findGist(token, page) {
      return gh("GET", "/gists?per_page=100&page=" + page, token).then(function (gists) {
        var hit = (gists || []).filter(function (g) { return g.files && g.files[GIST_FILE]; })[0];
        if (hit) return hit.id;
        if (!gists || gists.length < 100 || page >= 10) return null;
        return findGist(token, page + 1);
      });
    }

    function connect(token) {
      token = (token || "").trim();
      if (!token) return Promise.reject(new Error("請先貼上權杖"));
      setStatus("syncing", "連線中…");
      var login;
      return gh("GET", "/user", token).then(function (u) {
        login = u && u.login;
        return findGist(token, 1);
      }).then(function (gistId) {
        if (gistId) return gistId;
        var files = {};
        files[GIST_FILE] = { content: payload(load()) };
        return gh("POST", "/gists", token, {
          description: "stock-screener 我的關注（自動同步，請勿手動修改）", public: false, files: files,
        }).then(function (g) { return g.id; });
      }).then(function (gistId) {
        // seenAt=0：第一次連線時本機若有資料，會跟雲端合併，不會蓋掉任何一邊。
        // 舊版存的選單沒有修改時間（updatedAt=0），先標成「有修改」，才不會被雲端那份直接蓋掉。
        var local = load();
        if (!isEmpty(local) && !local.updatedAt) { local.updatedAt = 1; writeLocal(local); }
        setCfg({ token: token, gistId: gistId, login: login || "", seenAt: 0 });
        return run();
      }).catch(function (e) {
        setStatus("error", errMsg(e));
        throw e;
      });
    }

    function disconnect() {
      clearTimeout(timer);
      setCfg(null);
      setStatus("off");
    }

    function schedule() {
      if (!cfg()) return;
      clearTimeout(timer);
      setStatus("syncing", "等待上傳…");
      timer = setTimeout(function () { timer = null; run(); }, 800);
    }

    // 關掉頁面 / 切到別的 App 前，還沒上傳的修改立刻送出
    function flush() {
      if (timer) { clearTimeout(timer); timer = null; run(true); }
    }

    if (cfg()) status = { state: "syncing", msg: "準備同步…", at: null };

    return {
      enabled: function () { return !!cfg(); },
      info: function () { var c = cfg(); return c ? { login: c.login, gistId: c.gistId } : null; },
      status: function () { return status; },
      onStatus: function (fn) { listeners.push(fn); },
      connect: connect, disconnect: disconnect, schedule: schedule, flush: flush, pull: run,
      TOKEN_URL: TOKEN_URL, _merge: merge,
    };
  })();

  // 打開頁面時、從別的 App 切回來時，抓雲端最新版；有變動就叫畫面重畫
  function autoPull(onChange) {
    function pull() {
      if (!Sync.enabled()) return;
      Sync.pull().then(function (changed) { if (changed) onChange(); });
    }
    pull();
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") pull(); else Sync.flush();
    });
    window.addEventListener("pagehide", Sync.flush);
  }

  // ---------------- 報表頁：卡片上的「☆ 關注」按鈕 ----------------
  var openMenu = null;

  function closeMenu() {
    if (openMenu) { openMenu.remove(); openMenu = null; }
  }

  function refreshButton(btn, code) {
    var inLists = listsContaining(load(), code);
    btn.textContent = inLists.length ? "★ 已關注" : "☆ 關注";
    btn.classList.toggle("wl-on", inLists.length > 0);
    btn.title = inLists.length ? "在：" + inLists.map(function (l) { return l.name; }).join("、") : "加入自設選單";
  }

  function showMenu(btn, code) {
    closeMenu();
    var state = load();
    var menu = el("div", "wl-menu");
    menu.appendChild(el("div", "wl-menu-title", "加入到選單"));
    state.lists.forEach(function (l) {
      var item = el("button", "wl-menu-item");
      item.type = "button";
      var on = l.codes.indexOf(code) >= 0;
      item.textContent = (on ? "✓ " : "　 ") + l.name + "（" + l.codes.length + "）";
      item.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var s = load();
        toggleCode(s, l.id, code);
        save(s);
        refreshButton(btn, code);
        showMenu(btn, code); // 重畫勾勾
      });
      menu.appendChild(item);
    });
    var manage = el("a", "wl-menu-link", "管理我的關注 →");
    manage.href = btn.getAttribute("data-wl-href") || "watchlist.html";
    menu.appendChild(manage);
    menu.addEventListener("click", function (ev) { ev.stopPropagation(); });
    btn.parentNode.appendChild(menu);
    openMenu = menu;
  }

  function initReportPage(watchlistHref) {
    var cards = document.querySelectorAll(".card[data-code]");
    var buttons = [];
    Array.prototype.forEach.call(cards, function (card) {
      var code = card.getAttribute("data-code");
      var wrap = el("div", "wl-wrap");
      var btn = el("button", "wl-btn");
      btn.type = "button";
      btn.setAttribute("data-wl-href", watchlistHref);
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        if (openMenu && openMenu.parentNode === wrap) closeMenu(); else showMenu(btn, code);
      });
      wrap.appendChild(btn);
      card.appendChild(wrap);
      refreshButton(btn, code);
      buttons.push([btn, code]);
    });
    document.addEventListener("click", closeMenu);
    autoPull(function () {
      closeMenu();
      buttons.forEach(function (b) { refreshButton(b[0], b[1]); });
    });
  }

  // ---------------- 關注頁 ----------------
  function initWatchlistPage(root) {
    var data = { date: "", stocks: {} };
    try {
      var node = document.getElementById("wl-data");
      if (node) data = JSON.parse(node.textContent);
    } catch (e) { /* 沒有當天資料也能管理選單 */ }
    var stocks = data.stocks || {};
    var AL = data.al || null; // 分析標籤表（analysis.LABELS）

    function render() {
      var state = load();
      var curId = getCurrent();
      var cur = state.lists.filter(function (l) { return l.id === curId; })[0] || state.lists[0];
      root.innerHTML = "";

      // 選單分頁
      var tabs = el("div", "wl-tabs");
      state.lists.forEach(function (l) {
        var t = el("button", "wl-tab" + (l.id === cur.id ? " active" : ""), l.name + "（" + l.codes.length + "）");
        t.type = "button";
        t.addEventListener("click", function () {
          setCurrent(l.id); render();
        });
        tabs.appendChild(t);
      });
      var add = el("button", "wl-tab wl-tab-add", "＋ 新增選單");
      add.type = "button";
      add.disabled = state.lists.length >= MAX_LISTS;
      add.title = add.disabled ? "最多 " + MAX_LISTS + " 個選單" : "";
      add.addEventListener("click", function () {
        var name = window.prompt("新選單名稱（最多 " + MAX_NAME_LEN + " 字）", "選單" + (state.lists.length + 1));
        if (name == null) return;
        name = name.trim().slice(0, MAX_NAME_LEN);
        if (!name) return;
        var s = load();
        if (s.lists.length >= MAX_LISTS) return;
        var nl = { id: newId(), name: name, codes: [] };
        s.lists.push(nl); save(s); setCurrent(nl.id); render();
      });
      tabs.appendChild(add);
      root.appendChild(tabs);
      root.appendChild(el("div", "wl-hint", "選單 " + state.lists.length + " / " + MAX_LISTS));

      // 選單操作列
      var bar = el("div", "wl-bar");
      var rename = el("button", "wl-small", "✏️ 改名");
      rename.type = "button";
      rename.addEventListener("click", function () {
        var name = window.prompt("新的選單名稱（最多 " + MAX_NAME_LEN + " 字）", cur.name);
        if (name == null) return;
        name = name.trim().slice(0, MAX_NAME_LEN);
        if (!name) return;
        var s = load();
        s.lists.forEach(function (l) { if (l.id === cur.id) l.name = name; });
        save(s); render();
      });
      bar.appendChild(rename);
      var del = el("button", "wl-small wl-danger", "🗑 刪除選單");
      del.type = "button";
      del.disabled = state.lists.length <= 1;
      del.title = del.disabled ? "至少要保留一個選單" : "";
      del.addEventListener("click", function () {
        if (!window.confirm("確定刪除「" + cur.name + "」？裡面的 " + cur.codes.length + " 檔會一起移除。")) return;
        var s = load();
        s.lists = s.lists.filter(function (l) { return l.id !== cur.id; });
        save(s); setCurrent(null); render();
      });
      bar.appendChild(del);
      root.appendChild(bar);

      // 輸入代號加入
      var form = el("form", "wl-add");
      var input = el("input");
      input.type = "text";
      input.placeholder = "輸入股票代號，例如 2330";
      input.inputMode = "text";
      input.maxLength = 10;
      var submit = el("button", "wl-small", "加入");
      submit.type = "submit";
      var msg = el("div", "wl-hint");
      form.appendChild(input); form.appendChild(submit);
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var code = input.value.trim().toUpperCase();
        if (!code) return;
        var s = load();
        var target = s.lists.filter(function (l) { return l.id === cur.id; })[0];
        if (target.codes.indexOf(code) >= 0) { msg.textContent = code + " 已經在這個選單裡"; return; }
        target.codes.push(code); save(s); render();
      });
      root.appendChild(form);
      root.appendChild(msg);

      // 股票清單
      if (!cur.codes.length) {
        root.appendChild(el("div", "empty", "這個選單還是空的。可以在上面輸入代號，或到波段／當沖名單的卡片上按「☆ 關注」。"));
        return;
      }
      var grid = el("div", "grid");
      cur.codes.forEach(function (code) {
        var info = stocks[code];
        var card = el("div", "card");
        var top = el("div", "card-top");
        var left = el("div");
        left.appendChild(el("div", "name", info ? info.n : code));
        left.appendChild(el("div", "code", info ? code : "今天沒有這檔的收盤資料"));
        top.appendChild(left);
        if (info) {
          var price = el("div", "price");
          price.appendChild(el("div", "close", info.c.toFixed(2)));
          price.appendChild(el("div", info.p >= 0 ? "change-up" : "change-down",
            (info.p >= 0 ? "+" : "") + info.p.toFixed(2) + "%"));
          top.appendChild(price);
        }
        card.appendChild(top);
        var tags = el("div", "conds");
        if (info && info.s) tags.appendChild(el("span", "cond pass", "波段：" + info.s));
        if (info && info.d) tags.appendChild(el("span", "cond pass", "當沖：" + info.d));
        if (info && !info.s && !info.d) tags.appendChild(el("span", "cond", "今天不在波段／當沖名單"));
        card.appendChild(tags);
        if (info && info.a && AL) card.appendChild(analysisBlock(info.a));
        var rm = el("button", "wl-small wl-danger wl-remove", "移除");
        rm.type = "button";
        rm.addEventListener("click", function () {
          var s = load(); toggleCode(s, cur.id, code); save(s); render();
        });
        card.appendChild(rm);
        grid.appendChild(card);
      });
      root.appendChild(grid);
    }

    // 匯出 / 匯入（換手機、換電腦時搬移用）
    var io = document.getElementById("wl-io");
    if (io) {
      var box = el("textarea", "wl-io-box");
      box.rows = 3;
      box.hidden = true;
      var ok = el("button", "wl-small", "確認匯入");
      ok.type = "button";
      ok.hidden = true;
      var ioMsg = el("div", "wl-hint");
      var exp = el("button", "wl-small", "匯出選單");
      exp.type = "button";
      exp.addEventListener("click", function () {
        box.hidden = false; ok.hidden = true;
        box.value = JSON.stringify({ lists: load().lists });
        box.focus(); box.select();
        ioMsg.textContent = "把這段文字複製起來，到另一台裝置按「匯入選單」貼上。";
        try {
          navigator.clipboard.writeText(box.value).then(function () {
            ioMsg.textContent = "已複製到剪貼簿，到另一台裝置按「匯入選單」貼上即可。";
          }, function () {});
        } catch (e) { /* 不支援剪貼簿就手動複製 */ }
      });
      var imp = el("button", "wl-small", "匯入選單");
      imp.type = "button";
      imp.addEventListener("click", function () {
        box.hidden = false; ok.hidden = false;
        box.value = ""; box.focus();
        ioMsg.textContent = "貼上匯出的文字後按「確認匯入」（會覆蓋這台裝置目前的選單）。";
      });
      ok.addEventListener("click", function () {
        try {
          var parsed = JSON.parse(box.value);
          if (!parsed || !Array.isArray(parsed.lists)) throw new Error("bad");
          save(sanitize(parsed));
          box.hidden = true; ok.hidden = true;
          ioMsg.textContent = "匯入完成。";
          render();
        } catch (e) {
          ioMsg.textContent = "格式不對，請確認貼上的是完整的匯出文字。";
        }
      });
      io.appendChild(exp); io.appendChild(imp); io.appendChild(box); io.appendChild(ok); io.appendChild(ioMsg);
    }

    // 📊 短線分析表：a = analysis.to_compact() 的陣列
    // [price, trend, chips, vp, s1, s2, s3, r1, r2, buy1, buy2, nochase, stop, defend, target, rr, advice, weak, est]
    var DOT = { g: "🟢", y: "🟡", o: "🟠", r: "🔴", n: "⚪" };
    function analysisBlock(a) {
      var trend = AL.t[a[1]], chips = AL.c[a[2]], vp = AL.v[a[3]];
      var advice = AL.a[a[16]] + (a[17] ? AL.w : "");
      var det = el("details", "wl-an");
      det.appendChild(el("summary", null, "📊 " + trend[0] + "・" + chips[0] + "・量價" + vp[0] + "｜" + advice));
      var rows = [
        ["最新股價", a[0] + "元"],
        ["短線趨勢", trend], ["籌碼", chips], ["量價", vp],
        ["第一支撐", a[4] + "元"], ["第二支撐", a[5] + "元"], ["強支撐", a[6] + "元"],
        ["第一壓力", a[7] + "元"], ["第二壓力", a[8] + "元"],
        ["建議買點", a[9] + "元"], ["第二買點", a[10] + "元"], ["不宜追價", a[11] + "元以上"],
        ["短線停損", a[12] + "元"], ["最終防守", a[13] + "元"],
        ["第一停利", a[7] + "元"], ["第二停利", a[8] + "元"], ["波段目標", a[14] + "元"],
        ["風險報酬比", a[15]], ["操作建議", advice],
      ];
      var table = el("table");
      rows.forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("th", null, r[0]));
        var td = el("td");
        if (Array.isArray(r[1])) {
          td.className = "dot-" + r[1][1];
          td.textContent = (DOT[r[1][1]] || "") + " " + r[1][0];
        } else {
          td.textContent = r[1];
        }
        tr.appendChild(td);
        table.appendChild(tr);
      });
      det.appendChild(table);
      var note = "依 " + (data.date ? data.date.slice(0, 4) + "-" + data.date.slice(4, 6) + "-" + data.date.slice(6) : "") +
        " 收盤資料自動計算，僅供參考。";
      if (a[18]) note += "股價在近期高點之上，壓力與目標是用平均波幅（ATR）推估。";
      det.appendChild(el("div", "wl-an-note", note));
      return det;
    }

    var syncBox = document.getElementById("wl-sync");
    if (syncBox) initSyncPanel(syncBox, render);

    render();
    autoPull(render);
  }

  // ---------------- 關注頁：雲端同步設定 ----------------
  function initSyncPanel(box, rerender) {
    function draw() {
      box.innerHTML = "";
      box.appendChild(el("div", "wl-sync-title", "☁️ 手機／電腦自動同步"));
      var info = Sync.info();
      var st = Sync.status();
      if (!info) {
        box.appendChild(el("div", "wl-hint",
          "目前選單只存在這台裝置。每台裝置第一次使用時貼上同一個 GitHub 權杖，之後就會自動同步。"));
        var steps = el("ol", "wl-steps");
        var s1 = el("li");
        s1.appendChild(document.createTextNode("用電腦或手機登入 GitHub，點 "));
        var link = el("a", null, "建立權杖（已預先只勾 gist）");
        link.href = Sync.TOKEN_URL; link.target = "_blank"; link.rel = "noopener";
        s1.appendChild(link);
        s1.appendChild(document.createTextNode("，Expiration 選 No expiration（或你想要的期限），拉到最下面按 Generate token，複製 ghp_ 開頭那串。"));
        steps.appendChild(s1);
        steps.appendChild(el("li", null, "貼到下面按「連線同步」。另一台裝置也貼同一串（請自己留存，GitHub 只顯示一次）。"));
        box.appendChild(steps);
        var form = el("form", "wl-add");
        var input = el("input");
        input.type = "password"; input.placeholder = "貼上 GitHub 權杖（ghp_…）"; input.autocomplete = "off";
        var btn = el("button", "wl-small", "連線同步");
        btn.type = "submit";
        form.appendChild(input); form.appendChild(btn);
        form.addEventListener("submit", function (ev) {
          ev.preventDefault();
          btn.disabled = true;
          Sync.connect(input.value).then(function () { rerender(); draw(); }, function () { btn.disabled = false; draw(); });
        });
        box.appendChild(form);
        if (st.state === "error" || st.state === "syncing") box.appendChild(el("div", "wl-hint wl-sync-" + st.state, st.msg));
        return;
      }
      var line = "已連線" + (info.login ? "（GitHub：" + info.login + "）" : "") + "　";
      if (st.state === "ok") line += "✓ 已同步 " + st.at.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" });
      else line += st.msg;
      box.appendChild(el("div", "wl-hint wl-sync-" + st.state, line));
      var bar = el("div", "wl-bar");
      var now = el("button", "wl-small", "立即同步");
      now.type = "button";
      now.addEventListener("click", function () { Sync.pull().then(function (changed) { if (changed) rerender(); }); });
      var off = el("button", "wl-small wl-danger", "中斷這台裝置的同步");
      off.type = "button";
      off.addEventListener("click", function () {
        if (!window.confirm("中斷後這台裝置的權杖會刪除，選單保留在本機，雲端那份也不會被刪。確定？")) return;
        Sync.disconnect(); draw();
      });
      bar.appendChild(now); bar.appendChild(off);
      box.appendChild(bar);
    }
    Sync.onStatus(draw);
    draw();
  }

  // ---------------- 啟動 ----------------
  document.addEventListener("DOMContentLoaded", function () {
    var root = document.getElementById("wl-root");
    if (root) {
      initWatchlistPage(root);
    } else {
      var script = document.querySelector("script[data-wl-href]");
      initReportPage(script ? script.getAttribute("data-wl-href") : "watchlist.html");
    }
  });
})();
