from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from nitaq.agent import AgentConfig, MizanAgent
from nitaq.agent.i18n import detect_language
from nitaq.ui import build_dashboard_payload, render_answer_card, render_dashboard


ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="نطاق Nitaq",
    page_icon=":material/all_inclusive:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.html(ROOT / "nitaq" / "ui" / "theme.css")

SUGGESTIONS = {
    "ar": {
        ":material/warehouse: أين أفتح مستودعًا؟": "وش أفضل مدينة أفتح فيها مستودع؟",
        ":material/compare_arrows: قارن الرياض ومكة": "قارن طلبات التوصيل والمستودعات بين الرياض ومكة",
        ":material/description: اشتراطات المستودعات": "وش أهم اشتراطات المستودعات اللوجستية؟",
    },
    "en": {
        ":material/warehouse: Where should I open a warehouse?": "Where should I open a warehouse?",
        ":material/compare_arrows: Compare Riyadh and Makkah": "Compare delivery demand and warehouses in Riyadh and Makkah.",
        ":material/description: Warehouse requirements": "What are the main logistics warehouse requirements?",
    },
}

UI_TEXT = {
    "ar": {
        "subtitle": "مساعد الأدلة والقرارات اللوجستية",
        "offline": "وضع محلي",
        "connected": "متصل",
        "new_chat": "محادثة جديدة",
        "ask_title": "ابدأ بسؤال لوجستي",
        "intro": "نطاق يفهم هدفك، يجمع البيانات والوثائق المناسبة، ثم يشرح لك النتيجة وحدودها.",
        "academic": "نموذج جامعي · بيانات أساسية حتى 2024 · نتائج قابلة للتدقيق",
        "suggestions": "أسئلة مقترحة",
        "input": "اسأل نطاق عن منطقة أو مؤشر أو ميناء أو اشتراط…",
        "done": "اكتمل التحليل",
        "failed": "تعذر إكمال التحليل",
        "how": "كيف يعمل نطاق؟",
        "trusted": "مصادر موثقة",
        "trusted_note": "مصادر سعودية رسمية وسياق تجريبي موضح بحدوده عند استخدامه.",
        "footer": "معرفة موثقة. قرارات لوجستية أذكى.",
    },
    "en": {
        "subtitle": "Logistics evidence and decision assistant",
        "offline": "Local mode",
        "connected": "Connected",
        "new_chat": "New conversation",
        "ask_title": "Start with a logistics question",
        "intro": "Nitaq understands your goal, gathers the right data and documents, then explains the result and its limits.",
        "academic": "University project · Core data through 2024 · Auditable results",
        "suggestions": "Suggested questions",
        "input": "Ask Nitaq about a region, indicator, port, or requirement…",
        "done": "Analysis complete",
        "failed": "Analysis could not be completed",
        "how": "How Nitaq works",
        "trusted": "Trusted sources",
        "trusted_note": "Official Saudi sources, plus clearly labeled experimental context when used.",
        "footer": "Trusted knowledge. Smarter logistics.",
    },
}

HOW_IT_WORKS = {
    "ar": [
        ("understand", ":material/neurology:", "يفهم", "يقرأ هدفك وسياق المحادثة، ويفصل بين القرار المطلوب والمنطقة أو الميناء الذي تضيفه لاحقًا."),
        ("compare", ":material/balance:", "يقارن", "يستخدم أدوات Python للبيانات والأرقام، ويجمع أكثر من مصدر عندما يحتاج السؤال إلى تحليل مركب."),
        ("explain", ":material/visibility:", "يشرح", "يقدم جوابًا مباشرًا، ثم يضع التفاصيل والمصادر والقيود في طبقة اختيارية قابلة للمراجعة."),
    ],
    "en": [
        ("understand", ":material/neurology:", "Understand", "Interprets your goal and conversation context while keeping the decision separate from newly supplied places."),
        ("compare", ":material/balance:", "Compare", "Uses Python for numbers and combines multiple evidence sources when the question needs a compound analysis."),
        ("explain", ":material/visibility:", "Explain", "Leads with a direct answer, with detailed data, sources, and limitations available on demand."),
    ],
}

TRUSTED_SOURCES = ["GASTAT", "TGA", "Mawani", "Logisti", "MODON", "MOMAH", "IMF PortWatch"]


def _load_streamlit_secret() -> str | None:
    load_dotenv(ROOT / ".env", override=False)
    try:
        value = st.secrets.get("GROQ_API_KEY")
    except Exception:
        value = None
    if value and not os.getenv("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = str(value)
    return os.getenv("GROQ_API_KEY")


def _agent_code_version() -> int:
    """Invalidate the cached agent when routing or analytics modules change during development."""
    code_files = [
        *ROOT.joinpath("nitaq", "agent").glob("*.py"),
        *ROOT.joinpath("nitaq", "tools").glob("*.py"),
        *ROOT.joinpath("nitaq", "rag").glob("*.py"),
        *ROOT.joinpath("nitaq", "ui").glob("*.py"),
    ]
    return max((path.stat().st_mtime_ns for path in code_files), default=0)


@st.cache_resource(show_spinner=False, max_entries=4)
def _agent(offline: bool, code_version: int) -> MizanAgent:
    return MizanAgent(AgentConfig.from_env(ROOT), offline=offline)


def _initialise_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("conversation_id", str(uuid.uuid4()))
    st.session_state.setdefault("conversation_context", {})
    st.session_state.setdefault("nitaq_ui_language", "العربية")
    st.session_state.setdefault("pending_question", None)
    st.session_state.setdefault("pending_history", [])
    st.session_state.setdefault("intro_seen", False)


def _render_intro_logo() -> None:
    """Show a lightweight, CSS-only brand reveal once per browser session."""
    st.html(
        """
        <div class="nitaq-intro-overlay" aria-hidden="true">
          <div class="nitaq-intro-lockup">
            <div class="nitaq-intro-mark">∞</div>
            <div class="nitaq-intro-name">Nitaq</div>
            <div class="nitaq-intro-line"></div>
          </div>
        </div>
        """
    )


def _render_thinking_logo(label: str) -> None:
    """Keep slow model/tool work visibly alive without a heavy loading panel."""
    st.html(
        f"""
        <div class="nitaq-thinking" role="status" aria-label="{label}">
          <div class="nitaq-thinking-mark">∞</div>
          <div class="nitaq-thinking-copy">
            <strong>{label}</strong>
            <span class="nitaq-thinking-bar"></span>
          </div>
        </div>
        """
    )


def _clean_history_content(content: str) -> str:
    return content.split("\n\nالمصادر:", 1)[0].split("\n\nملاحظة:", 1)[0].strip()


def _history_for_agent() -> list[dict[str, str]]:
    """Keep only recent successful turns; failed answers never become context."""
    messages = st.session_state.messages
    successful_pairs: list[dict[str, str]] = []
    for index, item in enumerate(messages):
        if item.get("role") != "assistant" or index == 0:
            continue
        response = item.get("response") or {}
        if response.get("status") not in {"completed", "completed_fallback", "needs_clarification"}:
            continue
        previous = messages[index - 1]
        if previous.get("role") != "user":
            continue
        successful_pairs.extend(
            [
                {"role": "user", "content": previous["content"]},
                {"role": "assistant", "content": _clean_history_content(item["content"])},
            ]
        )
    return successful_pairs[-4:]


def _clear_conversation() -> None:
    st.session_state.messages = []
    st.session_state.conversation_id = str(uuid.uuid4())
    st.session_state.conversation_context = {}
    st.session_state.pending_question = None
    st.session_state.pending_history = []
    st.session_state.pop("nitaq_suggestion_ar", None)
    st.session_state.pop("nitaq_suggestion_en", None)


def _queue_question(question: str) -> None:
    """Persist the user turn before the slower model run starts."""
    cleaned = question.strip()
    if not cleaned or st.session_state.pending_question:
        return
    st.session_state.pending_history = _history_for_agent()
    st.session_state.messages.append({"role": "user", "content": cleaned})
    st.session_state.pending_question = cleaned


def _response_callout(response: dict[str, Any], language: str = "ar") -> None:
    status = response.get("status")
    if status == "provider_error":
        st.error("The analysis service is temporarily unavailable. Try again shortly." if language == "en" else "تعذر الاتصال بخدمة التحليل حاليًا. حاول مرة أخرى بعد قليل.", icon=":material/cloud_off:")
    elif status and status.startswith("blocked"):
        st.warning("The answer was stopped to protect evidence accuracy or usage boundaries." if language == "en" else "أوقف النظام الإجابة لحماية دقة الأرقام أو حدود الاستخدام.", icon=":material/gpp_maybe:")


def _details_label(payload: dict[str, Any], language: str = "ar") -> str:
    if payload.get("kind") == "knowledge":
        return "Show sources and pages" if language == "en" else "عرض المصادر والصفحات"
    if payload.get("tool") in {"screen_regions", "evaluate_warehouse_locations"}:
        return "Show decision rationale and evidence" if language == "en" else "عرض سبب الترشيح والأدلة"
    return "Show evidence and details" if language == "en" else "عرض الأدلة والتفاصيل"


def _loading_label(question: str, language: str = "ar") -> str:
    lowered = question.lower()
    if any(token in lowered for token in ("اشتراط", "لائحة", "دليل", "ما هي", "ماهي", "تعريف", "requirement", "regulation", "guide", "definition", "what is", "what are")):
        return "Nitaq is searching the documents…" if language == "en" else "نطاق يبحث في الوثائق…"
    if any(token in lowered for token in ("قارن", "أفضل", "اتجاه", "طلبات", "مستودع", "ميناء", "compare", "best", "trend", "delivery", "warehouse", "port")):
        return "Nitaq is analyzing the data…" if language == "en" else "نطاق يحلل البيانات…"
    return "Nitaq is understanding the question…" if language == "en" else "نطاق يفهم السؤال…"


_initialise_state()
if not st.session_state.intro_seen:
    _render_intro_logo()
    st.session_state.intro_seen = True
api_key = _load_streamlit_secret()
offline_flag = os.getenv("NITAQ_UI_OFFLINE", os.getenv("MIZAN_UI_OFFLINE", "0"))
developer_flag = os.getenv("NITAQ_UI_DEVELOPER_MODE", os.getenv("MIZAN_UI_DEVELOPER_MODE", "0"))
offline = offline_flag == "1" or not api_key
developer_mode = developer_flag == "1"
suggested_prompt: str | None = None
typed_prompt: str | None = None
ui_language = "en" if st.session_state.nitaq_ui_language == "English" else "ar"
text = UI_TEXT[ui_language]

with st.container(horizontal=True, horizontal_alignment="center"):
    app_shell = st.container(width=1180, key=f"nitaq_direction_{ui_language}")

with app_shell:
    with st.container(key="nitaq_header"):
        with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
            with st.container(gap=None):
                st.title("∞ Nitaq", anchor=False)
                st.caption(text["subtitle"])
            with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="right", gap="small"):
                selected_language = st.segmented_control(
                    "Language",
                    ["العربية", "English"],
                    key="nitaq_ui_language",
                    label_visibility="collapsed",
                )
                if offline:
                    st.badge(text["offline"], icon=":material/cloud_off:", color="orange")
                else:
                    st.badge(text["connected"], icon=":material/cloud_done:", color="green")
                if st.session_state.messages:
                    st.button(
                        text["new_chat"],
                        icon=":material/refresh:",
                        type="tertiary",
                        on_click=_clear_conversation,
                    )

    conversation = st.container(
        key="nitaq_conversation",
        height="content",
        border=False,
    )
    with conversation:
        if not st.session_state.messages:
            with st.container(key="nitaq_welcome", horizontal_alignment="center", gap="small"):
                st.subheader(text["ask_title"], anchor=False)
                st.caption(text["intro"])
                st.caption(text["academic"])
                typed_prompt = st.chat_input(
                    text["input"],
                    key=f"nitaq_chat_input_{ui_language}",
                    max_chars=4_000,
                    submit_mode="disable",
                    disabled=bool(st.session_state.pending_question),
                )
                selected = st.pills(
                    text["suggestions"],
                    list(SUGGESTIONS[ui_language]),
                    default=[],
                    key=f"nitaq_suggestion_{ui_language}",
                    label_visibility="collapsed",
                    width="stretch",
                )
                if selected:
                    suggested_prompt = SUGGESTIONS[ui_language][selected]

            st.space("small")
            with st.container(key="nitaq_how_it_works", gap="small"):
                st.subheader(text["how"], anchor=False)
                feature_columns = st.columns(3, vertical_alignment="top")
                for column, (feature_key, icon, heading, description) in zip(feature_columns, HOW_IT_WORKS[ui_language], strict=True):
                    with column:
                        with st.container(key=f"nitaq_feature_{feature_key}", height="stretch", gap="small"):
                            st.subheader(f"{icon} {heading}", anchor=False)
                            st.caption(description)

            with st.container(key="nitaq_sources", gap="small"):
                st.subheader(text["trusted"], anchor=False)
                st.caption(text["trusted_note"])
                with st.container(horizontal=True, gap="small"):
                    for source in TRUSTED_SOURCES:
                        st.badge(source, icon=":material/check:", color="orange")

        for message_index, message in enumerate(st.session_state.messages):
            avatar = ":material/person:" if message["role"] == "user" else ":material/travel_explore:"
            with st.chat_message(message["role"], avatar=avatar):
                if message.get("response"):
                    message_language = message["response"].get("language") or detect_language(message["content"])
                    payload = message.get("dashboard_payload") or {"kind": "empty", "tool": None}
                    render_answer_card(
                        message["content"],
                        message["response"],
                        payload,
                        key=f"answer_card_{message_index}",
                        language=message_language,
                    )
                    _response_callout(message["response"], message_language)
                    if payload.get("kind") != "empty":
                        with st.expander(
                            _details_label(payload, message_language),
                            expanded=False,
                            icon=":material/analytics:",
                        ):
                            render_dashboard(
                                payload,
                                message["response"],
                                developer_mode=developer_mode,
                                language=message_language,
                            )
                else:
                    st.markdown(message["content"])

        if st.session_state.pending_question:
            pending_question = st.session_state.pending_question
            prompt_language = detect_language(pending_question, ui_language)
            with st.chat_message("assistant", avatar=":material/travel_explore:"):
                loading_label = _loading_label(pending_question, prompt_language)
                _render_thinking_logo(loading_label)
                with st.status(loading_label, expanded=False) as status:
                    try:
                        response = _agent(offline, _agent_code_version()).ask(
                            pending_question,
                            history=st.session_state.pending_history,
                            conversation_id=st.session_state.conversation_id,
                            context=st.session_state.conversation_context,
                        )
                        response_dict = response.to_dict()
                        st.session_state.conversation_context = response_dict.get("context", {})
                        status.update(label=UI_TEXT[prompt_language]["done"], state="complete", expanded=False)
                    except Exception:
                        response_dict = {
                            "answer": (
                                "The request could not be completed because of a temporary error. The source data was not changed, and you can try again."
                                if prompt_language == "en"
                                else "تعذر إكمال الطلب بسبب خطأ مؤقت. البيانات الأصلية لم تتغير، ويمكن إعادة المحاولة."
                            ),
                            "status": "ui_error",
                            "model": "none",
                            "tool_trace": [],
                            "citations": [],
                            "limitations": [],
                            "missing_data_notes": [],
                            "context": st.session_state.conversation_context,
                            "language": prompt_language,
                        }
                        status.update(label=UI_TEXT[prompt_language]["failed"], state="error", expanded=False)
                    try:
                        dashboard_payload = build_dashboard_payload(response_dict)
                    except Exception:
                        dashboard_payload = {"kind": "empty", "tool": None}
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": response_dict["answer"],
                    "response": response_dict,
                    "dashboard_payload": dashboard_payload,
                }
            )
            st.session_state.pending_question = None
            st.session_state.pending_history = []
            st.rerun()

    if not st.session_state.messages:
        with st.container(key="nitaq_footer", horizontal=True, horizontal_alignment="center", vertical_alignment="center"):
            st.caption(f"∞  {text['footer']}")

if st.session_state.messages or st.session_state.pending_question:
    typed_prompt = st.chat_input(
        text["input"],
        key=f"nitaq_chat_input_{ui_language}",
        max_chars=4_000,
        submit_mode="disable",
        disabled=bool(st.session_state.pending_question),
    )

prompt = suggested_prompt or typed_prompt

if prompt:
    _queue_question(prompt)
    st.rerun()
