from pathlib import Path
import sys


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import streamlit as st

    from ai.common import LiveAccessError, get_connection, get_provider, live_access_status, load_settings, state_dir
    from ai.rag import answer_question, build_index, load_index

    st.set_page_config(page_title="Chat with Zomato reviews", page_icon="💬", layout="wide")
    st.title("Chat with your Zomato reviews")
    st.caption("Retrieve review excerpts, then ask for an answer with verifiable review-ID citations.")
    try:
        settings = load_settings()
        credit_status = live_access_status(settings)
        cache_path = state_dir() / "rag_reviews.sqlite3"
        index = load_index(cache_path, settings.embedding_model, settings.rag_sample_n, settings.max_review_chars)
    except Exception:
        st.error("The local RAG configuration or saved index could not be loaded. Check the setup guide without sharing credentials.")
        return

    if credit_status["allowed"]:
        st.caption(credit_status["message"])
    else:
        st.warning(credit_status["message"])
    st.info(
        f"This app uses at most {settings.rag_sample_n} non-empty reviews, selected deterministically by review ID. "
        f"Each excerpt is limited to {settings.max_review_chars} characters. Answers describe this sample, not all customers. "
        "Embeddings use the hosted text-embedding-3-small model. Building and asking use the configured credit controls."
    )
    if st.button("Build / refresh review index", type="primary", disabled=not credit_status["allowed"]):
        if not credit_status["allowed"]:
            st.warning(credit_status["message"])
            return
        try:
            with st.spinner("Reading the bounded review sample and embedding uncached excerpts…"):
                provider = get_provider()
                with get_connection(schema="STAGING", query_only=True) as connection:
                    index = build_index(
                        connection, provider, cache_path,
                        sample_n=settings.rag_sample_n,
                        embedding_model=settings.embedding_model,
                        max_review_chars=settings.max_review_chars,
                    )
            st.session_state.pop("rag_answer", None)
            st.success(f"Index ready: {len(index.reviews)} reviews. Matching cached embeddings were reused.")
        except LiveAccessError as error:
            st.warning(str(error))
        except (ValueError, RuntimeError):
            st.error("The index could not be refreshed. Check the configured access, available credit allowance, and local setup guide.")
        except Exception:
            st.error("The index could not be refreshed. Check the local setup and warehouse access; credentials are hidden.")

    if index is None:
        st.warning("Build the review index before asking a question. Opening this page does not query the warehouse or call the AI API.")
        return
    st.caption(
        f"Saved corpus: {len(index.reviews)} reviews · updated {index.refreshed_at} · "
        f"retrieving up to {settings.top_k} excerpts per question. Refresh explicitly to see warehouse changes."
    )
    with st.form("review_question"):
        question = st.text_area(
            "Ask about this review sample",
            placeholder="What do these reviews say about late delivery?",
            max_chars=settings.max_question_chars,
        )
        submitted = st.form_submit_button("Ask using retrieved reviews", disabled=not index.reviews or not credit_status["allowed"])
    if submitted:
        st.session_state.pop("rag_answer", None)
        if not credit_status["allowed"]:
            st.warning(credit_status["message"])
        elif not question.strip():
            st.warning("Enter a question first.")
        else:
            try:
                with st.spinner("Retrieving excerpts and checking the answer’s review citations…"):
                    result = answer_question(
                        question, index, get_provider(),
                        top_k=settings.top_k,
                        max_question_chars=settings.max_question_chars,
                    )
                st.session_state["rag_answer"] = result
            except LiveAccessError as error:
                st.warning(str(error))
            except (ValueError, RuntimeError):
                st.error("A grounded answer could not be verified. Check the credit allowance and setup, or try a narrower question.")
            except Exception:
                st.error("The question could not be completed. Check the local setup guide; credentials are hidden.")
    result = st.session_state.get("rag_answer")
    if result:
        st.subheader("Answer")
        st.text(result["answer"])
        if result["citations"]:
            st.caption("Verified review IDs: " + ", ".join(result["citations"]))
        st.caption("Citation checks verify IDs and formatting. They do not prove that every generated claim faithfully represents its source.")
        with st.expander("Retrieved source reviews", expanded=True):
            cited = set(result["citations"])
            st.dataframe(
                [{**source, "cited": source["review_id"] in cited} for source in result["sources"]],
                hide_index=True,
                use_container_width=True,
            )
        st.caption("Similarity ranks excerpts for this question; it is not a confidence score or a measure of customer-wide prevalence.")


if __name__ == "__main__":
    main()
