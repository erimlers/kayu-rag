// ==========================================================================
// KAYÜ MEVZUAT ASİSTANI — SSE STREAMING, GEÇMİŞ & MODERN CHATBOT İSTEMCİSİ
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
  const STORAGE_KEY = "kayu_rag_chats_v1";

  const appShell = document.getElementById("appShell");
  const sidebarScrim = document.getElementById("sidebarScrim");
  const sidebarToggleBtn = document.getElementById("sidebarToggleBtn");
  const historyList = document.getElementById("historyList");
  const topbarTitle = document.getElementById("topbarTitle");

  const askForm = document.getElementById("askForm");
  const questionInput = document.getElementById("questionInput");
  const submitBtn = document.getElementById("submitBtn");
  const chatViewport = document.getElementById("chatViewport");
  const welcomeCard = document.getElementById("welcomeCard");
  const messagesList = document.getElementById("messagesList");
  const newChatBtn = document.getElementById("newChatBtn");
  const suggestionCards = document.querySelectorAll(".suggestion-card");

  // Modal elementleri
  const docsModalBtn = document.getElementById("docsModalBtn");
  const sidebarDocsBtn = document.getElementById("sidebarDocsBtn");
  const docsModal = document.getElementById("docsModal");
  const closeModalBtn = document.getElementById("closeModalBtn");
  const docsSearchInput = document.getElementById("docsSearchInput");

  let activeAbortController = null;
  let isStreaming = false;
  let chats = loadChats();
  let currentChatId = null;

  renderHistoryList();

  // ------------------------------------------------------------------------
  // Kenar Çubuğu Aç / Kapat (Masaüstü & Mobil)
  // ------------------------------------------------------------------------
  function toggleSidebar() {
    if (window.innerWidth <= 820) {
      appShell.classList.toggle("sidebar-mobile-open");
    } else {
      appShell.classList.toggle("sidebar-collapsed");
    }
  }

  function closeMobileSidebar() {
    appShell.classList.remove("sidebar-mobile-open");
  }

  if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener("click", toggleSidebar);
  }
  if (sidebarScrim) {
    sidebarScrim.addEventListener("click", closeMobileSidebar);
  }

  // ------------------------------------------------------------------------
  // 19 Resmi Belge Modalı & Anlık Arama
  // ------------------------------------------------------------------------
  function openDocsModal() {
    if (!docsModal) return;
    docsModal.classList.add("open");
    docsModal.setAttribute("aria-hidden", "false");
    closeMobileSidebar();
    if (docsSearchInput) {
      docsSearchInput.value = "";
      filterDocsList("");
      setTimeout(() => docsSearchInput.focus(), 40);
    }
  }

  function closeDocsModal() {
    if (!docsModal) return;
    docsModal.classList.remove("open");
    docsModal.setAttribute("aria-hidden", "true");
  }

  if (docsModalBtn) docsModalBtn.addEventListener("click", openDocsModal);
  if (sidebarDocsBtn) sidebarDocsBtn.addEventListener("click", openDocsModal);
  if (closeModalBtn) closeModalBtn.addEventListener("click", closeDocsModal);

  if (docsModal) {
    docsModal.addEventListener("click", (e) => {
      if (e.target === docsModal) closeDocsModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && docsModal.classList.contains("open")) {
        closeDocsModal();
      }
    });
  }

  if (docsSearchInput) {
    docsSearchInput.addEventListener("input", (e) => filterDocsList(e.target.value));
  }

  function filterDocsList(query) {
    const q = query.trim().toLocaleLowerCase("tr-TR");
    document.querySelectorAll("#docsModalBody .doc-group").forEach((group) => {
      let visible = 0;
      group.querySelectorAll(".doc-row").forEach((row) => {
        const name = row.querySelector(".doc-row-name")?.textContent.toLocaleLowerCase("tr-TR") || "";
        const match = !q || name.includes(q);
        row.style.display = match ? "flex" : "none";
        if (match) visible++;
      });
      group.style.display = visible > 0 ? "flex" : "none";
    });
  }

  // ------------------------------------------------------------------------
  // Sohbet Geçmişi (localStorage)
  // ------------------------------------------------------------------------
  function loadChats() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function saveChats() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats.slice(0, 30)));
    } catch {
      // Depolama doluysa sessizce geç
    }
  }

  function ensureCurrentChat(firstQuestion) {
    if (currentChatId) {
      const existing = chats.find((c) => c.id === currentChatId);
      if (existing) return existing;
    }
    const id = "chat-" + Date.now();
    const title = firstQuestion.length > 44 ? firstQuestion.slice(0, 44) + "…" : firstQuestion;
    const chat = { id, title, updatedAt: Date.now(), messages: [] };
    chats.unshift(chat);
    currentChatId = id;
    if (topbarTitle) topbarTitle.textContent = title;
    saveChats();
    renderHistoryList();
    return chat;
  }

  function renderHistoryList() {
    if (!historyList) return;
    if (!chats.length) {
      historyList.innerHTML = '<div class="history-empty">Henüz kayıtlı sohbet yok.</div>';
      return;
    }

    historyList.innerHTML = "";
    chats.forEach((chat) => {
      const item = document.createElement("div");
      item.className = "history-item" + (chat.id === currentChatId ? " active" : "");
      item.innerHTML = `
        <span class="history-item-title">${escapeHtml(chat.title)}</span>
        <button class="history-delete-btn" type="button" title="Sohbeti sil" aria-label="Sohbeti sil">×</button>
      `;

      item.addEventListener("click", (e) => {
        if (e.target.closest(".history-delete-btn")) return;
        loadChatSession(chat.id);
        closeMobileSidebar();
      });

      const delBtn = item.querySelector(".history-delete-btn");
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        chats = chats.filter((c) => c.id !== chat.id);
        saveChats();
        if (currentChatId === chat.id) {
          resetToNewChat();
        } else {
          renderHistoryList();
        }
      });

      historyList.appendChild(item);
    });
  }

  function loadChatSession(chatId) {
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }
    setStreamingUI(false);

    const chat = chats.find((c) => c.id === chatId);
    if (!chat) return;

    currentChatId = chat.id;
    if (topbarTitle) topbarTitle.textContent = chat.title;
    messagesList.innerHTML = "";
    if (welcomeCard) welcomeCard.style.display = "none";

    chat.messages.forEach((m) => {
      if (m.role === "user") {
        appendUserMessage(m.text);
      } else {
        const turn = createBotTurn();
        turn.finalize(m.text, m.sources || [], m.elapsedMs, m.cached);
      }
    });

    renderHistoryList();
    scrollToBottom();
  }

  function resetToNewChat() {
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }
    setStreamingUI(false);
    currentChatId = null;
    if (topbarTitle) topbarTitle.textContent = "Yeni Sohbet";
    messagesList.innerHTML = "";
    if (welcomeCard) welcomeCard.style.display = "flex";
    questionInput.value = "";
    questionInput.style.height = "auto";
    questionInput.focus();
    renderHistoryList();
    chatViewport.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ------------------------------------------------------------------------
  // Giriş & Buton Olayları
  // ------------------------------------------------------------------------
  questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 140) + "px";
  });

  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isStreaming) {
        askForm.dispatchEvent(new Event("submit"));
      }
    }
  });

  suggestionCards.forEach((card) => {
    card.addEventListener("click", () => {
      const q = card.getAttribute("data-query");
      if (q && !isStreaming) {
        questionInput.value = q;
        questionInput.dispatchEvent(new Event("input"));
        askForm.dispatchEvent(new Event("submit"));
      }
    });
  });

  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      resetToNewChat();
      closeMobileSidebar();
    });
  }

  function setStreamingUI(active) {
    isStreaming = active;
    if (active) {
      submitBtn.disabled = false;
      submitBtn.classList.add("is-streaming");
      submitBtn.title = "Yanıtı durdur";
      submitBtn.setAttribute("aria-label", "Yanıtı durdur");
    } else {
      submitBtn.classList.remove("is-streaming");
      submitBtn.disabled = false;
      submitBtn.title = "Gönder";
      submitBtn.setAttribute("aria-label", "Soruyu Gönder");
    }
  }

  submitBtn.addEventListener("click", (e) => {
    if (isStreaming && activeAbortController) {
      e.preventDefault();
      activeAbortController.abort();
    }
  });

  // ------------------------------------------------------------------------
  // Form Gönderimi ve SSE Akış İşleme
  // ------------------------------------------------------------------------
  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isStreaming) return;

    const query = questionInput.value.trim();
    if (!query) return;

    if (welcomeCard) welcomeCard.style.display = "none";
    const activeChat = ensureCurrentChat(query);

    appendUserMessage(query);
    activeChat.messages.push({ role: "user", text: query });
    activeChat.updatedAt = Date.now();
    saveChats();

    questionInput.value = "";
    questionInput.style.height = "auto";
    setStreamingUI(true);

    const botTurn = createBotTurn();
    scrollToBottom();

    activeAbortController = new AbortController();
    let streamedRawText = "";
    let finished = false;

    try {
      const response = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
        signal: activeAbortController.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Sunucu hatası: HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;

          const payloadStr = line.slice(5).trim();
          if (!payloadStr) continue;

          let evt;
          try {
            evt = JSON.parse(payloadStr);
          } catch {
            continue;
          }

          if (evt.type === "status") {
            botTurn.setStatus(evt.message || "Hazırlanıyor...");
          } else if (evt.type === "reset") {
            streamedRawText = "";
            botTurn.reset(evt.message || "Alternatif model deneniyor...");
          } else if (evt.type === "chunk") {
            if (!streamedRawText) {
              botTurn.clearStatus();
            }
            streamedRawText += evt.text || "";
            botTurn.updateText(streamedRawText, true);
            scrollIfNearBottom();
          } else if (evt.type === "done") {
            finished = true;
            const finalText = evt.answer || streamedRawText;
            const sources = evt.sources || [];
            botTurn.finalize(finalText, sources, evt.elapsed_ms, evt.cached);
            activeChat.messages.push({
              role: "bot",
              text: finalText,
              sources,
              elapsedMs: evt.elapsed_ms,
              cached: evt.cached,
            });
            activeChat.updatedAt = Date.now();
            saveChats();
            scrollIfNearBottom();
          } else if (evt.type === "error") {
            finished = true;
            botTurn.showError(evt.message || "Yanıt alınırken bir hata oluştu.", query);
          }
        }
      }

      if (!finished && streamedRawText) {
        botTurn.finalize(streamedRawText, [], null, false);
        activeChat.messages.push({ role: "bot", text: streamedRawText, sources: [] });
        saveChats();
      }
    } catch (err) {
      if (err.name === "AbortError") {
        if (streamedRawText) {
          botTurn.finalize(streamedRawText, [], null, false);
        } else {
          botTurn.showError("Yanıt durduruldu.", query);
        }
      } else {
        botTurn.showError(`Bağlantı hatası: ${err.message}`, query);
      }
    } finally {
      activeAbortController = null;
      setStreamingUI(false);
      questionInput.focus();
    }
  });

  // ------------------------------------------------------------------------
  // Mesaj Balonları Oluşturucu
  // ------------------------------------------------------------------------
  function appendUserMessage(text) {
    const row = document.createElement("div");
    row.className = "msg-row user-row";
    row.innerHTML = `<div class="user-bubble">${escapeHtml(text)}</div>`;
    messagesList.appendChild(row);
  }

  function createBotTurn() {
    const row = document.createElement("div");
    row.className = "msg-row bot-row";
    row.innerHTML = `
      <div class="bot-avatar-wrap" aria-hidden="true">
        <img src="/api/logo" alt="" class="bot-avatar-img" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
        <span class="bot-avatar-fallback">K</span>
      </div>
      <div class="bot-bubble-col">
        <div class="bot-bubble">
          <div class="typing-status">
            <div class="typing-dots"><span></span><span></span><span></span></div>
            <span class="status-msg">Mevzuat taranıyor...</span>
          </div>
          <div class="response-prose"></div>
        </div>
      </div>
    `;
    messagesList.appendChild(row);

    const colEl = row.querySelector(".bot-bubble-col");
    const bubbleEl = row.querySelector(".bot-bubble");
    const statusEl = row.querySelector(".typing-status");
    const statusMsgEl = row.querySelector(".status-msg");
    const proseEl = row.querySelector(".response-prose");

    return {
      setStatus(msg) {
        if (statusMsgEl) statusMsgEl.textContent = msg;
      },
      reset(msg) {
        proseEl.innerHTML = "";
        if (!statusEl.parentNode) {
          bubbleEl.prepend(statusEl);
        }
        if (statusMsgEl) statusMsgEl.textContent = msg;
      },
      clearStatus() {
        if (statusEl && statusEl.parentNode) statusEl.remove();
      },
      updateText(rawText, streaming) {
        proseEl.innerHTML = renderMarkdown(rawText, streaming);
      },
      finalize(finalText, sources, elapsedMs, cached) {
        if (statusEl) statusEl.remove();
        proseEl.innerHTML = renderMarkdown(finalText, false);

        // Kaynak çekmecesi
        let citationsEl = null;
        if (sources && sources.length > 0) {
          citationsEl = document.createElement("div");
          citationsEl.className = "citations-wrapper";
          citationsEl.innerHTML = `
            <div class="citations-heading">Dayanak Resmi Kaynaklar (${sources.length})</div>
            <div class="citations-list">
              ${sources.map((src) => createCitationAccordionHtml(src)).join("")}
            </div>
          `;
          bubbleEl.appendChild(citationsEl);

          citationsEl.querySelectorAll(".source-accordion").forEach((acc) => {
            const summary = acc.querySelector(".source-summary");
            if (summary) {
              summary.addEventListener("click", () => acc.classList.toggle("open"));
            }
          });
        }

        // Metin içi atıf rozetleri tıklandığında ilgili kaynağı aç
        if (citationsEl) {
          proseEl.querySelectorAll(".doc-ref-badge").forEach((badge) => {
            badge.addEventListener("click", () => {
              const targetFile = badge.getAttribute("data-file");
              const targetPage = badge.getAttribute("data-page");
              const accordions = Array.from(citationsEl.querySelectorAll(".source-accordion"));
              const match =
                accordions.find(
                  (a) =>
                    a.getAttribute("data-file") === targetFile &&
                    (!targetPage || a.getAttribute("data-page") === targetPage)
                ) || accordions.find((a) => a.getAttribute("data-file") === targetFile);

              if (match) {
                match.classList.add("open", "highlight");
                match.scrollIntoView({ behavior: "smooth", block: "nearest" });
                setTimeout(() => match.classList.remove("highlight"), 1400);
              }
            });
          });
        }

        // Balon altı sessiz aksiyon barı
        const actionsRow = document.createElement("div");
        actionsRow.className = "bot-actions-row";

        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "btn-copy-inline";
        copyBtn.innerHTML = copyIconHtml("Kopyala");
        copyBtn.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(finalText);
            copyBtn.classList.add("copied");
            copyBtn.innerHTML = checkIconHtml("Kopyalandı");
            setTimeout(() => {
              copyBtn.classList.remove("copied");
              copyBtn.innerHTML = copyIconHtml("Kopyala");
            }, 1800);
          } catch {
            // Pano erişimi engellendiyse sessiz kal
          }
        });
        actionsRow.appendChild(copyBtn);

        const metaParts = [];
        if (cached) {
          metaParts.push("Önbellekten");
        }
        if (typeof elapsedMs === "number" && elapsedMs >= 0) {
          const sec = (elapsedMs / 1000).toFixed(elapsedMs < 100 ? 2 : 1);
          metaParts.push(`${sec} sn`);
        }
        if (metaParts.length > 0) {
          const stat = document.createElement("span");
          stat.className = "meta-stat";
          stat.textContent = metaParts.join(" · ");
          actionsRow.appendChild(stat);
        }

        colEl.appendChild(actionsRow);
      },
      showError(msg, retryQuery) {
        if (statusEl && statusEl.parentNode) statusEl.remove();
        const errDiv = document.createElement("div");
        errDiv.className = "error-inline";

        const msgSpan = document.createElement("span");
        msgSpan.textContent = msg;
        errDiv.appendChild(msgSpan);

        if (retryQuery) {
          const retryBtn = document.createElement("button");
          retryBtn.type = "button";
          retryBtn.className = "btn-retry";
          retryBtn.textContent = "Tekrar Dene";
          retryBtn.addEventListener("click", () => {
            if (isStreaming) return;
            questionInput.value = retryQuery;
            questionInput.dispatchEvent(new Event("input"));
            askForm.dispatchEvent(new Event("submit"));
          });
          errDiv.appendChild(retryBtn);
        }

        bubbleEl.appendChild(errDiv);
      },
    };
  }

  function createCitationAccordionHtml(src) {
    const fileName = escapeHtml(src.file || "yonetmelik.pdf");
    const pageNum = src.page !== undefined ? String(src.page) : "-";
    const text = escapeHtml(src.text || "");

    return `
      <div class="source-accordion" data-file="${fileName}" data-page="${escapeHtml(pageNum)}">
        <div class="source-summary">
          <div class="source-summary-left">
            <span class="source-pdf-name" title="${fileName}">${fileName}</span>
            <span class="source-page-badge">s. ${escapeHtml(pageNum)}</span>
          </div>
          <svg class="source-toggle-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
        <div class="source-details">${text}</div>
      </div>
    `;
  }

  function copyIconHtml(label) {
    return `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
      </svg>
      <span>${label}</span>
    `;
  }

  function checkIconHtml(label) {
    return `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true">
        <polyline points="20 6 9 17 4 12"></polyline>
      </svg>
      <span>${label}</span>
    `;
  }

  // ------------------------------------------------------------------------
  // Markdown İşleme
  // ------------------------------------------------------------------------
  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatInline(escapedLine) {
    let out = escapedLine;
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/\[([a-zA-Z0-9_\-]+\.pdf[^\]]*)\]/g, (_full, inner) => {
      const fileMatch = inner.match(/([a-zA-Z0-9_\-]+\.pdf)/);
      const pageMatch = inner.match(/s\.?\s*(\d+)/);
      const df = fileMatch ? fileMatch[1] : "";
      const dp = pageMatch ? pageMatch[1] : "";
      return `<button type="button" class="doc-ref-badge" data-file="${df}" data-page="${dp}">[${inner}]</button>`;
    });
    return out;
  }

  function renderMarkdown(md, streaming = false) {
    if (!md) return streaming ? '<span class="streaming-cursor"></span>' : "";
    const lines = escapeHtml(md).split("\n");
    let html = "";
    let listTag = null;

    const closeList = () => {
      if (listTag) {
        html += `</${listTag}>`;
        listTag = null;
      }
    };

    for (const rawLine of lines) {
      const trimmed = rawLine.trim();
      if (!trimmed) {
        closeList();
        continue;
      }

      if (trimmed.startsWith("### ")) {
        closeList();
        html += `<h4>${formatInline(trimmed.slice(4))}</h4>`;
      } else if (trimmed.startsWith("## ")) {
        closeList();
        html += `<h3>${formatInline(trimmed.slice(3))}</h3>`;
      } else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        if (listTag !== "ul") {
          closeList();
          html += "<ul>";
          listTag = "ul";
        }
        html += `<li>${formatInline(trimmed.slice(2))}</li>`;
      } else if (/^\d+\.\s/.test(trimmed)) {
        if (listTag !== "ol") {
          closeList();
          html += "<ol>";
          listTag = "ol";
        }
        html += `<li>${formatInline(trimmed.replace(/^\d+\.\s/, ""))}</li>`;
      } else {
        closeList();
        html += `<p>${formatInline(trimmed)}</p>`;
      }
    }

    closeList();

    if (streaming) {
      const cursor = '<span class="streaming-cursor"></span>';
      if (html.endsWith("</p>")) {
        html = html.slice(0, -4) + cursor + "</p>";
      } else if (html.endsWith("</li></ul>")) {
        html = html.slice(0, -10) + cursor + "</li></ul>";
      } else if (html.endsWith("</li></ol>")) {
        html = html.slice(0, -10) + cursor + "</li></ol>";
      } else {
        html += cursor;
      }
    }

    return html;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      chatViewport.scrollTo({
        top: chatViewport.scrollHeight,
        behavior: "smooth",
      });
    });
  }

  function scrollIfNearBottom() {
    const distanceFromBottom =
      chatViewport.scrollHeight - chatViewport.scrollTop - chatViewport.clientHeight;
    if (distanceFromBottom < 180) {
      chatViewport.scrollTop = chatViewport.scrollHeight;
    }
  }
});
