import re
import requests
import streamlit as st

st.set_page_config(page_title="書籍検索アプリ (openBD)", layout="wide")

st.title("書籍検索アプリ")
st.caption("タイトル検索は Open Library を使い、表紙画像などの詳細は openBD で取得します（登録不要・制限の少ない組み合わせ）。最大5件表示して確定できます。")


def normalize_isbn(isbn: str) -> str:
    """ハイフンや空白を削除して ISBN を正規化する（数字とXのみを残す）。"""
    if not isbn:
        return ""
    s = re.sub(r"[^0-9Xx]", "", isbn)
    return s.upper()


def isbn10_to_isbn13(isbn10: str) -> str:
    """ISBN-10 を ISBN-13 (978 prefix) に変換する。入力は10文字（チェックディジット含む）。"""
    isbn10 = normalize_isbn(isbn10)
    if len(isbn10) != 10:
        return ""
    core = isbn10[:-1]
    isbn13_body = "978" + core
    # 計算
    total = 0
    for i, ch in enumerate(isbn13_body):
        n = int(ch)
        total += n if i % 2 == 0 else n * 3
    check = (10 - (total % 10)) % 10
    return isbn13_body + str(check)


def extract_isbn13_from_ol_doc(doc: dict) -> list:
    """Open Library の検索結果ドキュメントから ISBN13 の候補リストを返す（可能なら変換を行う）。"""
    isbns = []
    for raw in doc.get("isbn", []) or []:
        s = normalize_isbn(raw)
        if len(s) == 13:
            isbns.append(s)
        elif len(s) == 10:
            conv = isbn10_to_isbn13(s)
            if conv:
                isbns.append(conv)
    return isbns


def search_openlibrary(title: str, limit: int = 20) -> list:
    """Open Library でタイトル検索し、ISBN13 のリスト（重複なし）を返す。"""
    if not title:
        return []
    url = "https://openlibrary.org/search.json"
    params = {"title": title, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.error(f"Open Library 検索でエラーが発生しました: {e}")
        return []

    docs = data.get("docs", [])
    isbn13s = []
    seen = set()
    for doc in docs:
        candidates = extract_isbn13_from_ol_doc(doc)
        for isbn in candidates:
            if isbn not in seen:
                seen.add(isbn)
                isbn13s.append({
                    "isbn13": isbn,
                    "title": doc.get("title") or "",
                    "author": ", ".join(doc.get("author_name", [])) if doc.get("author_name") else "",
                    "publisher": ", ".join(doc.get("publisher", [])) if doc.get("publisher") else "",
                })
    return isbn13s


def query_openbd(isbn_list: list) -> dict:
    """openBD に複数 ISBN を渡してメタ情報を取得する。返り値は isbn13 -> openbd_item (or None)。"""
    if not isbn_list:
        return {}
    # openBD はカンマ区切りで複数指定可能
    isbn_param = ",".join(isbn_list)
    url = "https://api.openbd.jp/v1/get"
    try:
        r = requests.get(url, params={"isbn": isbn_param}, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.error(f"openBD への問い合わせでエラーが発生しました: {e}")
        return {isbn: None for isbn in isbn_list}

    # openBD はリクエストした順に配列を返す（見つからない項目は null）
    mapping = {}
    for i, isbn in enumerate(isbn_list):
        try:
            item = data[i]
        except Exception:
            item = None
        mapping[isbn] = item
    return mapping


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
        st.session_state["results"] = []

        # 1) Open Library でタイトル検索して ISBN13 候補を収集
        ol_results = search_openlibrary(query, limit=20)
        if not ol_results:
            st.warning("検索結果が見つかりませんでした。別のタイトルで試してください。")
        else:
            # 2) 最初の候補から最大5個の ISBN を選んで openBD に問い合わせ
            candidates = ol_results[:20]  # ある程度広く取ってから cover のあるものを優先
            isbn_list = [c["isbn13"] for c in candidates]
            # 重複排除して最初の 10 程度を取る
            seen = set()
            ordered = []
            for s in isbn_list:
                if s not in seen:
                    seen.add(s)
                    ordered.append(s)
                if len(ordered) >= 10:
                    break

            # 問い合わせ
            openbd_map = query_openbd(ordered)

            # openBD の情報を優先して候補リストを作成（表紙があるものを前に）
            enriched = []
            for entry in candidates:
                isbn = entry["isbn13"]
                ob = openbd_map.get(isbn)
                cover = None
                ob_title = None
                ob_publisher = None
                if ob:
                    summary = ob.get("summary", {})
                    cover = summary.get("cover")
                    ob_title = summary.get("title")
                    ob_publisher = summary.get("publisher")
                item = {
                    "id": isbn,
                    "title": ob_title or entry.get("title") or "不明",
                    "authors": entry.get("author") or "不明",
                    "publisher": ob_publisher or entry.get("publisher") or "不明",
                    "image": cover,
                    "raw_openbd": ob,
                    "raw_ol": entry,
                }
                enriched.append(item)

            # 表紙があるものを先に、最大5件
            with_cover = [x for x in enriched if x["image"]]
            without = [x for x in enriched if not x["image"]]
            final = (with_cover + without)[:5]

            st.session_state["results"] = final

# 検索結果の表示と選択
if st.session_state["results"]:
    results = st.session_state["results"]

    labels = []
    for i, r in enumerate(results):
        label = f"{i+1}. {r['title']} — 著者: {r['authors']} — 出版社: {r['publisher']} — ISBN13: {r['id']}"
        labels.append(label)

    st.subheader("候補（最大5件、openBD の表紙優先）")
    selected_label = st.radio("一覧から選んでください", labels, key="choice_radio")
    selected_index = labels.index(selected_label)
    selected = results[selected_index]

    cols = st.columns([1, 2])
    with cols[0]:
        if selected["image"]:
            st.image(selected["image"], caption="表紙画像（openBD）", use_column_width=True)
        else:
            st.info("表紙画像は openBD に見つかりませんでした")
        st.write("表紙画像のURL:")
        st.code(selected["image"] or "取得できませんでした")

    with cols[1]:
        st.markdown("### 選択中の書籍（確定前）")
        st.write("正確なタイトル:", selected["title"])
        st.write("著者:", selected["authors"])
        st.write("出版社:", selected["publisher"])
        st.write("ISBN13:", selected["id"])

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
        st.write("ISBN13:", confirmed["id"])
        st.write("表紙画像のURL:")
        st.code(confirmed["image"] or "取得できませんでした")
        st.write("（必要ならここからコピーして別の処理に渡してください）")
