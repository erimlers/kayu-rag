// ==========================================================================
// KAYÜ MEVZUAT DANIŞMANI - SADE & KURUMSAL İSTEMCİ LOGIC (APP.JS)
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
  const askForm = document.getElementById("askForm");
  const questionInput = document.getElementById("questionInput");
  const submitBtn = document.getElementById("submitBtn");
  const chatViewport = document.getElementById("chatViewport");
  const welcomeCard = document.getElementById("welcomeCard");
  const messagesList = document.getElementById("messagesList");
  const newChatBtn = document.getElementById("newChatBtn");
  const topicCards = document.querySelectorAll(".topic-card");

  // 19 Resmi Belge Modalı Elementleri
  const docsModalBtn = document.getElementById("docsModalBtn");
  const docsModal = document.getElementById("docsModal");
  const closeModalBtn = document.getElementById("closeModalBtn");

  // Modal Açma / Kapama Olayları
  if (docsModalBtn && docsModal) {
    docsModalBtn.addEventListener("click", () => {
      docsModal.classList.add("open");
    });

    if (closeModalBtn) {
      closeModalBtn.addEventListener("click", () => {
        docsModal.classList.remove("open");
      });
    }

    docsModal.addEventListener("click", (e) => {
      if (e.target === docsModal) {
        docsModal.classList.remove("open");
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && docsModal.classList.contains("open")) {
        docsModal.classList.remove("open");
      }
    });
  }

  // Textarea otomatik yükseklik ayarlaması
  questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 130) + "px";
  });

  // Enter ile gönderim (Shift + Enter yeni satır)
  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      askForm.dispatchEvent(new Event("submit"));
    }
  });

  // Sık sorulan soru kartlarına tıklanması
  topicCards.forEach((card) => {
    card.addEventListener("click", () => {
      const q = card.getAttribute("data-query");
      if (q) {
        questionInput.value = q;
        questionInput.dispatchEvent(new Event("input"));
        askForm.dispatchEvent(new Event("submit"));
      }
    });
  });

  // Yeni Soru / Sohbeti Temizle
  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      messagesList.innerHTML = "";
      if (welcomeCard) {
        welcomeCard.style.display = "flex";
      }
      questionInput.value = "";
      questionInput.style.height = "auto";
      questionInput.focus();
      chatViewport.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // Form Gönderimi
  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = questionInput.value.trim();
    if (!query) return;

    // Karşılama kartını gizle
    if (welcomeCard) {
      welcomeCard.style.display = "none";
    }

    // Kullanıcı sorusunu arayüze ekle
    appendUserMessage(query);

    // Giriş kutusunu temizle
    questionInput.value = "";
    questionInput.style.height = "auto";
    submitBtn.disabled = true;

    // Yükleniyor durumunu ekle
    const loadingId = appendLoadingIndicator();
    scrollToBottom();

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
      });

      if (!response.ok) {
        throw new Error(`Sunucu hatası: HTTP ${response.status}`);
      }

      const data = await response.json();
      removeElement(loadingId);
      appendBotResponse(data);
    } catch (err) {
      removeElement(loadingId);
      appendErrorMessage(`Bağlantı hatası: ${err.message}. Lütfen sunucunun çalıştığını kontrol edin.`);
    } finally {
      submitBtn.disabled = false;
      questionInput.focus();
      scrollToBottom();
    }
  });

  // ------------------------------------------------------------------------
  // Arayüze Mesaj Ekleme Fonksiyonları
  // ------------------------------------------------------------------------

  function appendUserMessage(text) {
    const row = document.createElement("div");
    row.className = "chat-bubble-row user-row";
    row.innerHTML = `<div class="user-question-box">${escapeHtml(text)}</div>`;
    messagesList.appendChild(row);
  }

  function appendLoadingIndicator() {
    const id = "loading-" + Date.now();
    const row = document.createElement("div");
    row.id = id;
    row.className = "chat-bubble-row bot-row";
    row.innerHTML = `
      <div class="loading-card">
        <div class="spinner"></div>
        <span>Yönetmelik ve yönergeler taranıyor...</span>
      </div>
    `;
    messagesList.appendChild(row);
    return id;
  }

  function appendErrorMessage(msg) {
    const row = document.createElement("div");
    row.className = "chat-bubble-row bot-row";
    row.innerHTML = `
      <div class="bot-response-card" style="border-color: #fca5a5; background: #fff5f5;">
        <span style="font-weight: 700; color: #b91c1c;">Hata Bildirimi</span>
        <p style="margin-top: 4px; color: #991b1b; font-size: 0.9rem;">${escapeHtml(msg)}</p>
      </div>
    `;
    messagesList.appendChild(row);
  }

  function appendBotResponse(data) {
    const row = document.createElement("div");
    row.className = "chat-bubble-row bot-row";

    const formattedAnswer = renderMarkdown(data.answer || "");
    const modelTag = data.model || "Gemini 3.5 Flash";

    let citationsHtml = "";
    if (data.sources && data.sources.length > 0) {
      citationsHtml = `
        <div class="citations-wrapper">
          <div class="citations-heading">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <span>Kullanılan Resmi Kaynaklar (${data.sources.length} Belge)</span>
          </div>
          <div class="citations-list">
            ${data.sources.map((src, i) => createCitationAccordionHtml(src, i)).join("")}
          </div>
        </div>
      `;
    }

    row.innerHTML = `
      <div class="bot-response-card">
        <div class="response-card-header">
          <div class="bot-identity-group">
            <div class="bot-avatar">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
            </div>
            <span class="bot-title-text">KAYÜ Mevzuat Danışmanı</span>
          </div>
          <div class="response-header-actions">
            <span class="model-name-badge">${escapeHtml(modelTag)}</span>
            <button class="btn-copy-card" title="Yanıtı Panoya Kopyala">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span>Kopyala</span>
            </button>
          </div>
        </div>

        <div class="response-prose">
          ${formattedAnswer}
        </div>

        ${citationsHtml}
      </div>
    `;

    messagesList.appendChild(row);

    // Kopyalama butonu işlevi
    const copyBtn = row.querySelector(".btn-copy-card");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const textToCopy = data.answer || "";
        try {
          await navigator.clipboard.writeText(textToCopy);
          copyBtn.classList.add("copied");
          copyBtn.innerHTML = `
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>Kopyalandı!</span>
          `;
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            copyBtn.innerHTML = `
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span>Kopyala</span>
            `;
          }, 2000);
        } catch (e) {
          console.error("Panoya kopyalanamadı:", e);
        }
      });
    }

    // Akordiyon açma/kapama olayları
    const accordions = row.querySelectorAll(".source-accordion");
    accordions.forEach((acc) => {
      const summary = acc.querySelector(".source-summary");
      if (summary) {
        summary.addEventListener("click", () => {
          acc.classList.toggle("open");
        });
      }
    });
  }

  function createCitationAccordionHtml(src, index) {
    const fileName = escapeHtml(src.file || "yonetmelik.pdf");
    const pageNum = src.page !== undefined ? src.page : "-";
    const text = escapeHtml(src.text || "");

    return `
      <div class="source-accordion">
        <div class="source-summary">
          <div class="source-summary-left">
            <span class="source-pdf-name" title="${fileName}">${fileName}</span>
            <span class="source-page-badge">Sayfa ${pageNum}</span>
          </div>
          <span class="source-toggle-icon">▼</span>
        </div>
        <div class="source-details">${text}</div>
      </div>
    `;
  }

  // ------------------------------------------------------------------------
  // Markdown & Metin İşleme
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

  function renderMarkdown(md) {
    if (!md) return "";
    let safe = escapeHtml(md);

    // Kalın metin
    safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // İtalik metin
    safe = safe.replace(/\*(.*?)\*/g, "<em>$1</em>");

    // Kaynak atıfları: [belge.pdf, s.X]
    safe = safe.replace(
      /\[([a-zA-Z0-9_\-]+\.pdf(?:,\s*s\.\d+)?)\]/g,
      '<span class="doc-ref-badge">[$1]</span>'
    );

    const lines = safe.split("\n");
    let html = "";
    let inList = false;

    for (let line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        if (inList) {
          html += "</ul>";
          inList = false;
        }
        continue;
      }

      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        if (!inList) {
          html += "<ul>";
          inList = true;
        }
        html += `<li>${trimmed.substring(2)}</li>`;
      } else if (/^\d+\.\s/.test(trimmed)) {
        if (!inList) {
          html += "<ol>";
          inList = true;
        }
        html += `<li>${trimmed.replace(/^\d+\.\s/, "")}</li>`;
      } else {
        if (inList) {
          html += "</ul>";
          inList = false;
        }
        html += `<p>${trimmed}</p>`;
      }
    }

    if (inList) {
      html += "</ul>";
    }

    return html;
  }

  function removeElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function scrollToBottom() {
    setTimeout(() => {
      chatViewport.scrollTo({
        top: chatViewport.scrollHeight,
        behavior: "smooth"
      });
    }, 50);
  }
});
