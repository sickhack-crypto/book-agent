import re
import requests
import streamlit as st
import xml.etree.ElementTree as ET

st.set_page_config(page_title="書籍検索アプリ (NDL)", layout="wide")

st.title("書籍検索アプリ（国立国会図書館 + openBD）")
st.caption("NDL SRU で日本語タイトルを検索し、見つかった ISBN を openBD で照会して表紙画像を取得します。登録不要で日本の資料に強い組み合わせです。最大5件表示。")

NDL_SRU_URL = "https://iss.ndl.go.jp/api/sru"
OPENBD_URL = "https://api.openbd.jp/v1/get"


def parse_ndl_sru(xml_text: str):
    """NDL SRU の XML レスポンスをパースし、各 record の title, creator, publisher, identifier(isbn) を抽出します。
    戻り値はレコードのリスト: [{"title":..., "creator":..., "publisher":..., "identifiers": [..]}, ...]
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    ns = {
        "srw": "http://www.loc.gov/zing/srw/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    records = []
    for rec in root.findall(".//{http://www.loc.gov/zing/srw/}record"):
        data = rec.find("{http://www.loc.gov/zing/srw/}recordData")
        if data is None:
            continue
        # recordData 内の dc:* 要素を直接読む
        title = None
        creators = []
        publishers = []
        identifiers = []
        for child in data:
            tag = child.tag
            if tag.endswith("}title"):
                title = (child.text or "").strip()
            elif tag.endswith("}creator"):
                if child.text:
                    creators.append(child.text.strip())
            elif tag.endswith("}publisher"):
                if child.text:
                    publishers.append(child.text.strip())
            elif tag.endswith("}identifier"):
                if child.text:
                    identifiers.append(child.text.strip())
        records.append({
            "title": title or "",
            "creator": ", ".join(creators) if creators else "",
            "publisher": ", ".join(publishers) if publishers else "",
            "identifiers": identifiers,
        })
    return records


def extract_isbn13_list(identifiers: list) -> list:
    """identifier のリストから ISBN 相当の 13 桁を抽出し、正規化して返す。"""
    res = []
    for idf in identifiers:
        if not idf:
            continue
        s = re.sub(r"[^0-9Xx]", "", idf)
        if len(s) == 13:
            res.append(s)
        elif len(s) == 10:
            # ISBN-10 -> ISBN-13
            core = s[:-1]
            isbn13_body = "978" + core
            total = 0
            for i, ch in enumerate(isbn13_body):
                n = int(ch)
                total += n if i % 2 == 0 else n * 3
            check = (10 - (total % 10)) % 10
            res.append(isbn13_body + str(check))
    return res


def query_ndl_by_title(title: str, maximum_records: int = 20):
    """NDL SRU に title クエリで問い合わせて、パースしたレコードを返す。"""
    if not title:
        return []
    params = {
        "operation": "searchRetrieve",
        "query": f'title="{title}"',
        "maximumRecords": str(maximum_records),
    }
    try:
        r = requests.get(NDL_SRU_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.text
    except Exception as e:
        st.error(f"NDL 検索でエラーが発生しました: {e}")
        return []
    records = parse_ndl_sru(data)
    return records


def query_openbd_for_isbns(isbn13_list: list) -> dict:
    """openBD に ISBN13 のリストを渡してメタ情報を取得。返り値は isbn -> item(or None)。"""
    if not isbn13_list:
        return {}
    isbn_param = ",".join(isbn13_list)
    try:
        r = requests.get(OPENBD_URL, params={"isbn": isbn_param}, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.error(f"openBD 問い合わせでエラー: {e}")
        return {isbn: None for isbn in isbn13_list}
    mapping = {}
    for i, isbn in enumerate(isbn13_list):
        try:
            mapping[isbn] = data[i]
        except Exception:
            mapping[isbn] = None
    return mapping


# セッション初期化
if "results" not in st.session_state:
    st.session_state["results"] = []
if "confirmed" not in st.session_state:
    st.session_state["confirmed"] = None

with st.form("search_form"):
    query = st.text_input("本のタイトル（日本語可）を入力してください", "")
    submitted = st.form_submit_button("検索")
    if submitted:
        st.session_state["confirmed"] = None
        st.session_state["results"] = []

        ndl_records = query_ndl_by_title(query, maximum_records=30)
        if not ndl_records:
            st.warning("該当する結果が見つかりませんでした。別のタイトルで試してください。")
        else:
            # 各レコードから ISBN13 を抽出して優先度をつける
            candidates = []
            for rec in ndl_records:
                isbn13s = extract_isbn13_list(rec.get("identifiers", []))
                if not isbn13s:
                    # ISBN が無い場合でもタイトル/creator を候補表示できるようにする
                    candidates.append({
                        "isbn13": None,
                        "title": rec.get("title"),
                        "author": rec.get("creator"),
                        "publisher": rec.get("publisher"),
                        "ndl_raw": rec,
                    })
                else:
                    for i13 in isbn13s:
                        candidates.append({
                            "isbn13": i13,
                            "title": rec.get("title"),
                            "author": rec.get("creator"),
                            "publisher": rec.get("publisher"),
                            "ndl_raw": rec,
                        })

            # ISBN があるものを先にし、openBD で詳細（表紙）を取る
            isbn_list = [c["isbn13"] for c in candidates if c["isbn13"]][:20]
            openbd_map = query_openbd_for_isbns(isbn_list) if isbn_list else {}

            enriched = []
            for c in candidates:
                isbn = c.get("isbn13")
                cover = None
                ob_title = None
                ob_publisher = None
                if isbn and isbn in openbd_map and openbd_map[isbn]:
                    summary = openbd_map[isbn].get("summary", {})
                    cover = summary.get("cover")
                    ob_title = summary.get("title")
                    ob_publisher = summary.get("publisher")
                enriched.append({
                    "id": isbn or f"NDL-{len(enriched)}",
                    "title": ob_title or c.get("title") or "",
                    "authors": c.get("author") or "",
                    "publisher": ob_publisher or c.get("publisher") or "",
                    "image": cover,
                    "raw_ndl": c.get("ndl_raw"),
                    "raw_openbd": openbd_map.get(isbn) if isbn else None,
                })

            # 表紙のある順にし、最大5件
            with_cover = [x for x in enriched if x["image"]]
            without = [x for x in enriched if not x["image"]]
            final = (with_cover + without)[:5]
            st.session_state["results"] = final

# 表示と選択
if st.session_state["results"]:
    results = st.session_state["results"]
    labels = []
    for i, r in enumerate(results):
        label = f"{i+1}. {r['title']} — 著者: {r['authors']} — 出版社: {r['publisher']} — ID: {r['id']}"
        labels.append(label)

    st.subheader("候補（最大5件、表紙優先表示）")
    selected_label = st.radio("一覧から選んでください", labels, key="choice_radio")
    selected_index = labels.index(selected_label)
    selected = results[selected_index]

    cols = st.columns([1, 2])
    with cols[0]:
        if selected["image"]:
            st.image(selected["image"], caption="表紙画像", use_column_width=True)
        else:
            st.info("表紙画像は見つかりませんでした")
        st.write("表紙画像URL:")
        st.code(selected["image"] or "取得できませんでした")

    with cols[1]:
        st.markdown("### 選択中の書籍（確定前）")
        st.write("タイトル:", selected["title"])
        st.write("著者:", selected["authors"])
        st.write("出版社:", selected["publisher"])
        st.write("ID:", selected["id"])

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
        st.write("タイトル:", confirmed["title"])
        st.write("著者:", confirmed["authors"])
        st.write("出版社:", confirmed["publisher"])
        st.write("ID:", confirmed["id")
        st.write("表紙画像URL:")
        st.code(confirmed["image"] or "取得できませんでした")
