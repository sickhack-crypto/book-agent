import requests
import streamlit as st

st.set_page_config(page_title="書籍検索アプリ", layout="wide")

st.title("書籍検索アプリ")
st.caption("Google Books API を使ってタイトル候補を最大5件表示し、1件を選んで確定できます。")


def search_books(title: str, max_results: int = 5):
    """Google Books API でタイトル検索して候補を返す"""
    if not title:
        return []
    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": f"intitle:{title}", "maxResults": max_results}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        st.error(f"検索中にエラーが発生しました: {e}")
        return []

    items = data.get("items", [])
    results = []
    for item in items:
        info = item.get("volumeInfo", {})
        book_title = info.get("title", "不明")
        # サブタイトルがあれば結合して正確なタイトルとして扱う
        subtitle = info.get("subtitle")
        if subtitle:
            full_title = f"{book_title}: {subtitle}"
        else:
            full_title = book_title

        authors = info.get("authors") or []
        authors_text = ", ".join(authors) if authors else "不明"
        publisher = info.get("publisher", "不明")

        # 画像リンクは多種類あるので優先順位で取得
        image_url = None
        image_links = info.get("imageLinks", {})
        for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            if image_links.get(key):
                image_url = image_links.get(key)
                break

        # 一意にわかる識別子（もし必要なら）
        volume_id = item.get("id")

        results.append({
            "id": volume_id,
            "title": full_title,
            "authors": authors_text,
            "publisher": publisher,
            "image": image_url,
            "raw": info,
        })
    return results

# セッションステート初期化
if "results" not in st.session_state:
    st.session_state["results"] = []
if "confirmed" not in st.session_state:
    st.session_state["confirmed"] = None

with st.form("search_form"):
    query = st.text_input("本のタイトルを入力してください", "")
    submitted = st.form_submit_button("検索")
    if submitted:
        st.session_state["confirmed"] = None
        st.session_state["results"] = search_books(query, max_results=5)
        if not st.session_state["results"]:
            st.warning("該当する結果が見つかりませんでした。別のタイトルで試してください。")

# 検索結果の表示と選択
if st.session_state["results"]:
    results = st.session_state["results"]
    # 選択肢ラベルを作る
    labels = []
    for i, r in enumerate(results):
        label = f"{i+1}. {r['title']} — 著者: {r['authors']} — 出版社: {r['publisher']}"
        labels.append(label)

    st.subheader("候補（最大5件）")
    selected_label = st.radio("一覧から選んでください", labels, key="choice_radio")
    selected_index = labels.index(selected_label)
    selected = results[selected_index]

    # 右側に画像、左側に詳��を表示するレイアウト
    cols = st.columns([1, 2])
    with cols[0]:
        if selected["image"]:
            st.image(selected["image"], caption="表紙画像（プレビュー）", use_column_width=True)
        else:
            st.info("表紙画像は利用できません")
        st.write("表紙画像のURL:")
        st.code(selected["image"] or "取得できませんでした")

    with cols[1]:
        st.markdown("### 選択中の書籍（確定前）")
        st.write("正確なタイトル:", selected["title"])
        st.write("著者:", selected["authors"])
        st.write("出版社:", selected["publisher"])
        # 追加情報（必要なら）
        # st.write("Raw volumeInfo:", selected["raw"])

    if st.button("確定"):
        st.session_state["confirmed"] = selected
        st.success("選択を確定しました。下に確定内容を表示します。")

# 確定済みの表示
if st.session_state["confirmed"]:
    confirmed = st.session_state["confirmed"]
    st.markdown("---")
    st.subheader("確定済みの書籍情報")
    cols2 = st.columns([1, 2])
    with cols2[0]:
        if confirmed["image"]:
            st.image(confirmed["image"], caption="確定した表紙画像", use_column_width=True)
        else:
            st.info("表紙画像は利用できません")
    with cols2[1]:
        st.write("正確なタイトル:", confirmed["title"])
        st.write("著者:", confirmed["authors"])
        st.write("出版社:", confirmed["publisher"])
        st.write("表紙画像のURL:")
        st.code(confirmed["image"] or "取得できませんでした")
        st.write("（この情報を元に別の処理を行いたい場合は、ここからコピーしてください）")
