/*
 * 我的關注（自訂選單）
 * ====================
 * 選單存在「這個瀏覽器」的 localStorage 裡（GitHub Pages 是靜態網頁，沒有伺服器可以存）。
 * 手機跟電腦、不同瀏覽器各自一份；清除瀏覽器資料會一起清掉，可以用「匯出 / 匯入」搬移或備份。
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
  var memoryFallback = null; // localStorage 不能用（無痕模式等）時，至少本頁操作還能用

  function defaultState() {
    return { lists: [{ id: newId(), name: "我的關注", codes: [] }], current: null };
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
    return { lists: lists, current: typeof state.current === "string" ? state.current : null };
  }

  function load() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) return sanitize(JSON.parse(raw));
    } catch (e) { /* 讀不到就用預設 */ }
    if (!memoryFallback) {
      // 第一次使用：建立預設選單並馬上存起來，選單 id 才會固定（不然每次讀都是新的 id）
      save(defaultState());
    }
    return sanitize(memoryFallback);
  }

  function save(state) {
    memoryFallback = state;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) { /* 寫不進去時只保留在本頁記憶體 */ }
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
    });
    document.addEventListener("click", closeMenu);
  }

  // ---------------- 關注頁 ----------------
  function initWatchlistPage(root) {
    var data = { date: "", stocks: {} };
    try {
      var node = document.getElementById("wl-data");
      if (node) data = JSON.parse(node.textContent);
    } catch (e) { /* 沒有當天資料也能管理選單 */ }
    var stocks = data.stocks || {};

    function render() {
      var state = load();
      var cur = state.lists.filter(function (l) { return l.id === state.current; })[0] || state.lists[0];
      root.innerHTML = "";

      // 選單分頁
      var tabs = el("div", "wl-tabs");
      state.lists.forEach(function (l) {
        var t = el("button", "wl-tab" + (l.id === cur.id ? " active" : ""), l.name + "（" + l.codes.length + "）");
        t.type = "button";
        t.addEventListener("click", function () {
          var s = load(); s.current = l.id; save(s); render();
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
        s.lists.push(nl); s.current = nl.id; save(s); render();
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
        s.current = null; save(s); render();
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
        box.value = JSON.stringify(load());
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

    render();
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
