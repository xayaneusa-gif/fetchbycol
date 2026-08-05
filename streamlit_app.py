import csv
import io
import json
import html
import os
import random
import time
import zipfile
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REQUEST_FILE = "request.txt"
DETAIL_PASSWORD = "xayane"
MAX_RETRIES = 5
RETRY_BACKOFF = 1.0
APP_VERSION = "1.0.0"
OWNER_NAME = "Vikram"
APP_OWNER = "Hidden until you guess it"
APP_PURPOSE = "OD student fetch and export dashboard"


def load_request(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    method, path, _ = lines[0].split(maxsplit=2)

    headers = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    host = headers.get("Host")
    if not host:
        raise ValueError("Host header missing in request.txt")

    url = urljoin(f"https://{host}", path)

    headers.pop("Accept-Encoding", None)
    headers.pop("Connection", None)

    return method, url, headers


def update_regno_in_url(url, reg_no):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["regNo"] = [str(reg_no)]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )


def build_session():
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        status=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def mask_phone(phone):
    if not phone:
        return "-"
    phone = str(phone)
    if len(phone) < 4:
        return "***"
    return phone[:2] + "******" + phone[-2:]


def mask_email(email):
    if not email or "@" not in str(email):
        return "-"
    name, domain = str(email).split("@", 1)
    return name[:2] + "***@" + domain


def pretty_date(value):
    if not value:
        return "-"
    return str(value)[:10]


def money(value):
    try:
        return f"₹{float(value):,.0f}"
    except Exception:
        return "₹0"


def to_float(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None


def percent(obtained, maximum):
    obtained_value = to_float(obtained)
    maximum_value = to_float(maximum)
    if obtained_value is None or maximum_value in [None, 0]:
        return None
    return (obtained_value / maximum_value) * 100


def get_basic_value(data, key, masked=False):
    value = data.get(key)
    if masked and key == "phone":
        return mask_phone(value)
    if masked and key == "email":
        return mask_email(value)
    if key in {"dob", "doa"}:
        return pretty_date(value)
    return value if value not in [None, ""] else "-"


def basic_fields(data, masked=False):
    return [
        ("Name", get_basic_value(data, "name", masked)),
        ("College Roll Number OD", get_basic_value(data, "regNo", masked)),
        ("Gender", get_basic_value(data, "gender", masked)),
        ("DOB", get_basic_value(data, "dob", masked)),
        ("Phone", get_basic_value(data, "phone", masked)),
        ("Email", get_basic_value(data, "email", masked)),
        ("Father", get_basic_value(data, "fatherName", masked)),
        ("Mother", get_basic_value(data, "motherName", masked)),
        ("Course", get_basic_value(data, "course", masked)),
        ("Stream", get_basic_value(data, "stream", masked)),
        ("Batch", get_basic_value(data, "batch", masked)),
        ("Section", get_basic_value(data, "section", masked)),
        ("Category", get_basic_value(data, "category", masked)),
        ("Session", get_basic_value(data, "session", masked)),
        ("Address", get_basic_value(data, "address", masked)),
        ("City", get_basic_value(data, "city", masked)),
        ("State", get_basic_value(data, "state", masked)),
        ("Country", get_basic_value(data, "country", masked)),
        ("Pin Code", get_basic_value(data, "pinCode", masked)),
        ("Nationality", get_basic_value(data, "nationality", masked)),
        ("Religion", get_basic_value(data, "religion", masked)),
        ("Social Category", get_basic_value(data, "socialCategory", masked)),
        ("Admission Date", get_basic_value(data, "doa", masked)),
        ("Old/New", get_basic_value(data, "oldNew", masked)),
        ("SRN", get_basic_value(data, "srn", masked)),
        ("Application No", get_basic_value(data, "applicationNumber", masked)),
        ("Branch", get_basic_value(data, "branchId", masked)),
    ]


def detected_education_levels(data):
    levels = []
    index = 1
    while True:
        prefix = f"educationDetails{index}"
        if any(key.startswith(prefix) for key in data.keys()):
            levels.append(index)
            index += 1
        else:
            break
    return levels


def flatten_data(data, prefix=""):
    rows = []
    hidden_keywords = ["phone", "mobile", "email"]
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if key.lower() in hidden_keywords:
            continue
        if isinstance(value, dict):
            rows.extend(flatten_data(value, full_key))
        elif isinstance(value, list):
            rows.append((full_key, json.dumps(value, ensure_ascii=False)))
        else:
            rows.append((full_key, value if value not in [None, ""] else "-"))
    return rows


def safe_html(value):
    if value is None or value == "":
        return "-"
    return html.escape(str(value))


def fetch_student(session, base_url, headers, reg_no):
    url = update_regno_in_url(base_url, reg_no)
    response = session.request(
        method="GET",
        url=url,
        headers=headers,
        allow_redirects=True,
        timeout=30,
    )
    content_type = response.headers.get("Content-Type", "").lower()
    if "json" not in content_type and not response.text.lstrip().startswith("{"):
        raise ValueError(f"Non-JSON response for {reg_no}: {response.status_code}")
    data = response.json()
    data["_http_status"] = response.status_code
    data["_source_url"] = response.url
    return data


def fetch_students(session, base_url, headers, start_reg, end_reg):
    results = []
    failures = []
    total = end_reg - start_reg + 1
    progress = st.progress(0)
    status = st.empty()

    for index, reg_no in enumerate(range(start_reg, end_reg + 1), start=1):
        status.info(f"Fetching {reg_no} ({index}/{total})")
        try:
            data = fetch_student(session, base_url, headers, reg_no)
            results.append(data)
        except Exception as exc:
            failures.append({"regNo": reg_no, "error": str(exc)})
        progress.progress(index / total)
        time.sleep(0.2)

    status.empty()
    progress.empty()
    return results, failures


def filter_students(students, query):
    if not query:
        return students

    query = query.lower().strip()
    filtered = []
    for student in students:
        haystack = " ".join(
            str(student.get(field, ""))
            for field in [
                "regNo",
                "name",
                "course",
                "batch",
                "section",
                "category",
                "session",
                "stream",
                "branchId",
            ]
        ).lower()
        if query in haystack:
            filtered.append(student)
    return filtered


def basic_csv_bytes(students):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    headers = [
        "Photo",
        "Name",
        "College Roll Number OD",
        "Gender",
        "DOB",
        "Phone",
        "Email",
        "Father",
        "Mother",
        "Course",
        "Stream",
        "Batch",
        "Section",
        "Category",
        "Session",
        "Address",
        "City",
        "State",
        "Country",
        "Pin Code",
        "Nationality",
        "Religion",
        "Social Category",
        "Admission Date",
        "Old/New",
        "SRN",
        "Application No",
        "Branch",
    ]
    writer.writerow(headers)
    for student in students:
        writer.writerow(
            [
                student.get("photo") or "-",
                *[value for _, value in basic_fields(student, masked=True)],
            ]
        )
    return buffer.getvalue().encode("utf-8")


def detailed_zip_bytes(students):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(
            "students_detailed.json",
            json.dumps(students, indent=4, ensure_ascii=False),
        )
        zip_file.writestr("students_detailed.html", detailed_html_report(students))
    archive.seek(0)
    return archive.getvalue()


def basic_html(students, title="Basic Student Report"):
    rows = []
    for student in students:
        values = basic_fields(student, masked=True)
        cells = "".join(f"<div class='info'><span class='label'>{safe_html(label)}:</span> {safe_html(value)}</div>" for label, value in values)
        photo = student.get("photo")
        photo_html = f"<img class='photo' src='{safe_html(photo)}' alt='Student Photo'>" if photo else "<div class='photo'></div>"
        rows.append(
            f"""
            <div class="card">
                <div class="top">
                    {photo_html}
                    <div>
                        <div class="name">{safe_html(student.get("name"))}</div>
                        <div class="reg">Reg No: {safe_html(student.get("regNo"))}</div>
                    </div>
                </div>
                <div class="info"><span class="label">Gender:</span> {safe_html(student.get("gender"))}</div>
                <div class="info"><span class="label">DOB:</span> {safe_html(pretty_date(student.get("dob")))}</div>
                <div class="info"><span class="label">Phone:</span> {safe_html(mask_phone(student.get("phone")))}</div>
                <div class="info"><span class="label">Email:</span> {safe_html(mask_email(student.get("email")))}</div>
                <hr>
                <div class="info"><span class="label">Father:</span> {safe_html(student.get("fatherName"))}</div>
                <div class="info"><span class="label">Mother:</span> {safe_html(student.get("motherName"))}</div>
                <hr>
                <div class="info"><span class="label">Course:</span> {safe_html(student.get("course"))}</div>
                <div class="info"><span class="label">Stream:</span> {safe_html(student.get("stream"))}</div>
                <div class="info"><span class="label">Batch:</span> {safe_html(student.get("batch"))}</div>
                <div class="info"><span class="label">Section:</span> {safe_html(student.get("section"))}</div>
                <div class="info"><span class="label">Category:</span> {safe_html(student.get("category"))}</div>
                <div class="info"><span class="label">Session:</span> {safe_html(student.get("session"))}</div>
                <div class="info"><span class="label">Address:</span> {safe_html(student.get("address"))}</div>
                <div class="info"><span class="label">City:</span> {safe_html(student.get("city"))}</div>
                <div class="info"><span class="label">State:</span> {safe_html(student.get("state"))}</div>
                <div class="info"><span class="label">Country:</span> {safe_html(student.get("country"))}</div>
                <div class="info"><span class="label">Pin Code:</span> {safe_html(student.get("pinCode"))}</div>
                <div class="info"><span class="label">Nationality:</span> {safe_html(student.get("nationality"))}</div>
                <div class="info"><span class="label">Religion:</span> {safe_html(student.get("religion"))}</div>
                <div class="info"><span class="label">Social Category:</span> {safe_html(student.get("socialCategory"))}</div>
                <div class="info"><span class="label">Admission Date:</span> {safe_html(pretty_date(student.get("doa")))}</div>
                <div class="info"><span class="label">Old/New:</span> {safe_html(student.get("oldNew"))}</div>
                <div class="info"><span class="label">SRN:</span> {safe_html(student.get("srn"))}</div>
                <div class="info"><span class="label">Application No:</span> {safe_html(student.get("applicationNumber"))}</div>
                <div class="info"><span class="label">Branch:</span> {safe_html(student.get("branchId"))}</div>
            </div>
            """
        )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f6f8;
                padding: 20px;
            }}
            .card {{
                background: white;
                padding: 18px;
                border-radius: 14px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
                margin-bottom: 18px;
            }}
            .top {{
                display: flex;
                gap: 15px;
                align-items: center;
                margin-bottom: 15px;
            }}
            .photo {{
                width: 90px;
                height: 90px;
                object-fit: cover;
                border-radius: 50%;
                border: 2px solid #ddd;
                background: #eee;
            }}
            .name {{
                font-size: 22px;
                font-weight: bold;
            }}
            .reg {{
                color: #666;
            }}
            .info {{
                margin: 7px 0;
                font-size: 14px;
            }}
            .label {{
                font-weight: bold;
            }}
            hr {{
                border: none;
                border-top: 1px solid #eee;
                margin: 14px 0;
            }}
        </style>
    </head>
    <body>
        <h1>{title}</h1>
        {''.join(rows)}
    </body>
    </html>
    """


def detailed_html_report(students, title="Detailed Student Report", unlocked=False):
    cards = []
    for student in students:
        photo = student.get("photo")
        photo_html = f"<img class='photo' src='{safe_html(photo)}' alt='Student Photo'>" if photo else "<div class='photo'></div>"
        total_amount, total_received, total_concession, total_due, demand = fee_summary(student)
        education_blocks = []
        for level in detected_education_levels(student):
            pct = percent(
                student.get(f"educationDetails{level}ObtainedMarks"),
                student.get(f"educationDetails{level}MaxMarks"),
            )
            education_blocks.append(
                f"""
                <div class="block">
                    <h3>{safe_html(student.get(f"educationDetails{level}Class") or f"Education {level}")}</h3>
                    <div>Board / University: {safe_html(student.get(f"educationDetails{level}University"))}</div>
                    <div>School: {safe_html(student.get(f"educationDetails{level}School"))}</div>
                    <div>Roll No: {safe_html(student.get(f"educationDetails{level}RollNo"))}</div>
                    <div>Marks: {safe_html(student.get(f"educationDetails{level}ObtainedMarks"))}/{safe_html(student.get(f"educationDetails{level}MaxMarks"))}</div>
                    <div>Percentage: {safe_html(f'{pct:.2f}%' if pct is not None else '-')}</div>
                    <div>Passing Year: {safe_html(student.get(f"educationDetails{level}PassingYear"))}</div>
                    <div>Result: {safe_html(student.get(f"educationDetails{level}Result"))}</div>
                </div>
                """
            )

        fee_rows = "".join(
            f"""
            <tr>
                <td>{safe_html(item.get("feeHead"))}</td>
                <td>{safe_html(item.get("installment"))}</td>
                <td>₹{safe_html(item.get("amount", 0))}</td>
                <td>₹{safe_html(item.get("received", 0))}</td>
                <td>₹{safe_html(item.get("concession", 0))}</td>
                <td>₹{safe_html(item.get("amount", 0) - item.get("received", 0) - item.get("concession", 0))}</td>
            </tr>
            """
            for item in demand
        )

        cards.append(
            f"""
            <div class="container">
                <div class="header">
                    {photo_html}
                    <div>
                        <h1>{safe_html(student.get("name"))}</h1>
                        <div>Reg No: {safe_html(student.get("regNo"))}</div>
                        <div>{safe_html(student.get("course"))} | {safe_html(student.get("batch"))} | Section {safe_html(student.get("section"))}</div>
                    </div>
                </div>

                <div class="section">
                    <h2>Personal Info</h2>
                    <div class="grid">
                        <div class="item"><span class="label">Name:</span> {safe_html(student.get("name"))}</div>
                        <div class="item"><span class="label">Reg No:</span> {safe_html(student.get("regNo"))}</div>
                        <div class="item"><span class="label">Gender:</span> {safe_html(student.get("gender"))}</div>
                        <div class="item"><span class="label">DOB:</span> {safe_html(pretty_date(student.get("dob")))}</div>
                        <div class="item"><span class="label">Phone:</span> {safe_html(student.get("phone") if unlocked else mask_phone(student.get("phone")))}</div>
                        <div class="item"><span class="label">Email:</span> {safe_html(student.get("email") if unlocked else mask_email(student.get("email")))}</div>
                        <div class="item"><span class="label">Father:</span> {safe_html(student.get("fatherName"))}</div>
                        <div class="item"><span class="label">Mother:</span> {safe_html(student.get("motherName"))}</div>
                        <div class="item"><span class="label">Address:</span> {safe_html(student.get("address"))}</div>
                        <div class="item"><span class="label">City:</span> {safe_html(student.get("city"))}</div>
                        <div class="item"><span class="label">State:</span> {safe_html(student.get("state"))}</div>
                        <div class="item"><span class="label">Country:</span> {safe_html(student.get("country"))}</div>
                        <div class="item"><span class="label">Pin Code:</span> {safe_html(student.get("pinCode"))}</div>
                        <div class="item"><span class="label">Nationality:</span> {safe_html(student.get("nationality"))}</div>
                        <div class="item"><span class="label">Religion:</span> {safe_html(student.get("religion"))}</div>
                        <div class="item"><span class="label">Social Category:</span> {safe_html(student.get("socialCategory"))}</div>
                    </div>
                </div>

                <div class="section">
                    <h2>Academic Info</h2>
                    <div class="grid">
                        <div class="item"><span class="label">Course:</span> {safe_html(student.get("course"))}</div>
                        <div class="item"><span class="label">Stream:</span> {safe_html(student.get("stream"))}</div>
                        <div class="item"><span class="label">Batch:</span> {safe_html(student.get("batch"))}</div>
                        <div class="item"><span class="label">Section:</span> {safe_html(student.get("section"))}</div>
                        <div class="item"><span class="label">Session:</span> {safe_html(student.get("session"))}</div>
                        <div class="item"><span class="label">Category:</span> {safe_html(student.get("category"))}</div>
                        <div class="item"><span class="label">Branch:</span> {safe_html(student.get("branchId"))}</div>
                        <div class="item"><span class="label">SRN:</span> {safe_html(student.get("srn"))}</div>
                        <div class="item"><span class="label">Application No:</span> {safe_html(student.get("applicationNumber"))}</div>
                        <div class="item"><span class="label">Admission Date:</span> {safe_html(pretty_date(student.get("doa")))}</div>
                        <div class="item"><span class="label">Old/New:</span> {safe_html(student.get("oldNew"))}</div>
                        <div class="item"><span class="label">Promoted Status:</span> {safe_html(student.get("promotedStatus"))}</div>
                    </div>
                </div>

                <div class="section">
                    <h2>Fee Summary</h2>
                    <div class="grid">
                        <div class="item"><span class="label">Total Amount:</span> {money(total_amount)}</div>
                        <div class="item"><span class="label">Received:</span> {money(total_received)}</div>
                        <div class="item"><span class="label">Concession:</span> {money(total_concession)}</div>
                        <div class="item"><span class="label">Due:</span> {money(total_due)}</div>
                    </div>
                    <table>
                        <tr>
                            <th>Fee Head</th>
                            <th>Installment</th>
                            <th>Amount</th>
                            <th>Received</th>
                            <th>Concession</th>
                            <th>Due</th>
                        </tr>
                        {fee_rows}
                    </table>
                </div>

                <div class="section">
                    <h2>Education Details</h2>
                    <div class="grid">
                        {''.join(education_blocks) if education_blocks else '<div class="item">No education data.</div>'}
                    </div>
                </div>

                <div class="section">
                    <h2>Complete JSON Data</h2>
                    <pre>{safe_html(json.dumps(student, indent=4, ensure_ascii=False))}</pre>
                </div>
            </div>
            """
        )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f6f8;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 16px;
                padding: 24px;
                max-width: 1100px;
                margin: auto;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
                margin-bottom: 24px;
            }}
            .header {{
                display: flex;
                gap: 20px;
                align-items: center;
            }}
            .photo {{
                width: 130px;
                height: 130px;
                border-radius: 50%;
                object-fit: cover;
                background: #eee;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                gap: 10px;
            }}
            .item, .block {{
                background: #f8fafc;
                padding: 12px;
                border-radius: 10px;
            }}
            .section {{
                margin-top: 28px;
            }}
            pre {{
                white-space: pre-wrap;
                background: #111827;
                color: #e5e7eb;
                padding: 16px;
                border-radius: 12px;
                overflow-x: auto;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #ddd;
                text-align: left;
            }}
            th {{
                background: #eef2f7;
            }}
            h1 {{
                margin-bottom: 5px;
            }}
        </style>
    </head>
    <body>
        {''.join(cards)}
    </body>
    </html>
    """


def fee_summary(student):
    demand = student.get("studentDemand", {}).get("demand", [])
    total_amount = sum(item.get("amount", 0) for item in demand)
    total_received = sum(item.get("received", 0) for item in demand)
    total_concession = sum(item.get("concession", 0) for item in demand)
    total_due = total_amount - total_received - total_concession
    return total_amount, total_received, total_concession, total_due, demand


def render_basic_card(student):
    photo = student.get("photo")
    photo_col, info_col = st.columns([1, 4])

    with photo_col:
        if photo:
            st.image(photo, use_container_width=True)
        else:
            st.info("No photo")

    with info_col:
        fields = basic_fields(student, masked=True)
        left, right = st.columns(2)
        for index, (label, value) in enumerate(fields):
            with left if index % 2 == 0 else right:
                st.markdown(f"**{label}:** {value}")


def render_detail_view(student, unlocked):
    st.subheader("Selected Student Detail")
    if not unlocked:
        st.info("Enter the password in the sidebar to unlock the detailed view.")

    photo = student.get("photo")
    phone = student.get("phone") if unlocked else mask_phone(student.get("phone"))
    email = student.get("email") if unlocked else mask_email(student.get("email"))

    total_amount, total_received, total_concession, total_due, demand = fee_summary(student)

    header_cols = st.columns([1, 3])
    with header_cols[0]:
        if photo:
            st.image(photo, use_container_width=True)
        else:
            st.info("No photo")
    with header_cols[1]:
        st.markdown(f"**Name:** {student.get('name') or '-'}")
        st.markdown(f"**College Roll Number OD:** {student.get('regNo') or '-'}")
        st.markdown(f"**Gender:** {student.get('gender') or '-'}")
        st.markdown(f"**DOB:** {pretty_date(student.get('dob'))}")
        st.markdown(f"**Phone:** {phone}")
        st.markdown(f"**Email:** {email}")
        st.markdown(f"**Father:** {student.get('fatherName') or '-'}")
        st.markdown(f"**Mother:** {student.get('motherName') or '-'}")

    st.markdown("### Academic Info")
    academic_cols = st.columns(2)
    academic_items = [
        ("Course", student.get("course")),
        ("Stream", student.get("stream")),
        ("Batch", student.get("batch")),
        ("Section", student.get("section")),
        ("Session", student.get("session")),
        ("Category", student.get("category")),
        ("Branch", student.get("branchId")),
        ("SRN", student.get("srn")),
        ("Application No", student.get("applicationNumber")),
        ("Admission Date", pretty_date(student.get("doa"))),
        ("Old/New", student.get("oldNew")),
        ("Promoted Status", student.get("promotedStatus")),
    ]
    for index, (label, value) in enumerate(academic_items):
        with academic_cols[index % 2]:
            st.markdown(f"**{label}:** {value or '-'}")

    st.markdown("### Fee Summary")
    fee_cols = st.columns(4)
    fee_cols[0].metric("Total Amount", money(total_amount))
    fee_cols[1].metric("Received", money(total_received))
    fee_cols[2].metric("Concession", money(total_concession))
    fee_cols[3].metric("Due", money(total_due))

    if demand:
        st.dataframe(
            [
                {
                    "Fee Head": item.get("feeHead"),
                    "Installment": item.get("installment"),
                    "Amount": item.get("amount", 0),
                    "Received": item.get("received", 0),
                    "Concession": item.get("concession", 0),
                    "Due": item.get("amount", 0) - item.get("received", 0) - item.get("concession", 0),
                }
                for item in demand
            ],
            use_container_width=True,
            hide_index=True,
        )

    if unlocked:
        st.markdown("### Education Details")
        for level in detected_education_levels(student):
            with st.expander(student.get(f"educationDetails{level}Class") or f"Education {level}", expanded=False):
                st.markdown(f"**Board / University:** {student.get(f'educationDetails{level}University') or '-'}")
                st.markdown(f"**School:** {student.get(f'educationDetails{level}School') or '-'}")
                st.markdown(f"**Roll No:** {student.get(f'educationDetails{level}RollNo') or '-'}")
                st.markdown(f"**Marks:** {student.get(f'educationDetails{level}ObtainedMarks') or '-'} / {student.get(f'educationDetails{level}MaxMarks') or '-'}")
                st.markdown(f"**Passing Year:** {student.get(f'educationDetails{level}PassingYear') or '-'}")
                st.markdown(f"**Result:** {student.get(f'educationDetails{level}Result') or '-'}")

        st.markdown("### Raw JSON")
        st.json(student)


def ensure_state():
    defaults = {
        "fetched_students": [],
        "fetch_failures": [],
        "fetch_mode": "Single",
        "previous_fetch_mode": "Single",
        "has_fetched": False,
        "detail_unlocked": False,
        "detail_error": "",
        "selected_index": 0,
        "owner_unlocked": False,
        "owner_feedback": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def sync_fetch_mode_state():
    current_mode = st.session_state.fetch_mode
    previous_mode = st.session_state.previous_fetch_mode

    if current_mode != previous_mode:
        st.session_state.fetched_students = []
        st.session_state.fetch_failures = []
        st.session_state.selected_index = 0
        st.session_state.has_fetched = False
        st.session_state.detail_unlocked = False
        st.session_state.detail_error = ""

    st.session_state.previous_fetch_mode = current_mode


def handle_owner_guess():
    guess = st.session_state.owner_guess.strip()
    if guess.lower() == OWNER_NAME.lower():
        st.session_state.owner_unlocked = True
        st.session_state.owner_feedback = "Shh... don't tell anyone you solved it."
    else:
        st.session_state.owner_unlocked = False
        st.session_state.owner_feedback = random.choice(
            [
                "Not quite. Try again.",
                "Close, but not there yet.",
                "Keep going, you've got this.",
                "That one missed the mark. Another try?",
                "Nice effort. Give it one more shot.",
            ]
        )


def reset_owner_guess():
    st.session_state.owner_unlocked = False
    st.session_state.owner_feedback = ""
    st.session_state.owner_guess = ""


def run_fetch():
    method, base_url, headers = load_request(REQUEST_FILE)
    session = build_session()

    fetch_mode = st.session_state.fetch_mode
    if fetch_mode == "Single":
        reg_no = st.session_state.single_reg_no
        start_reg = end_reg = reg_no
    else:
        start_reg = st.session_state.start_reg_no
        end_reg = st.session_state.end_reg_no
        if start_reg > end_reg:
            raise ValueError("Start reg no cannot be greater than end reg no")

    results, failures = fetch_students(session, base_url, headers, start_reg, end_reg)
    st.session_state.fetched_students = results
    st.session_state.fetch_failures = failures
    st.session_state.selected_index = 0
    st.session_state.has_fetched = True


def main():
    st.set_page_config(page_title="OD Fetch Dashboard", layout="wide")
    ensure_state()

    st.title("OD Student Fetch Dashboard")
    st.caption("Single or range fetch, search, password-protected details, and downloads in one Streamlit app.")

    with st.sidebar:
        st.markdown(f"**Owner:** {OWNER_NAME if st.session_state.owner_unlocked else APP_OWNER}")
        st.markdown(f"**App:** {APP_PURPOSE}")

        st.text_input("Guess the owner name", key="owner_guess", placeholder="Type the owner's name")
        owner_try_col, owner_reset_col = st.columns(2)
        owner_try_col.button("Try", on_click=handle_owner_guess)
        owner_reset_col.button("Reset", on_click=reset_owner_guess)

        if st.session_state.owner_feedback:
            if st.session_state.owner_unlocked:
                st.success(st.session_state.owner_feedback)
            else:
                st.warning(st.session_state.owner_feedback)

        st.header("Fetch Controls")
        st.session_state.fetch_mode = st.selectbox("Search mode", ["Single", "Range"], index=0 if st.session_state.fetch_mode == "Single" else 1)
        sync_fetch_mode_state()

        with st.form("fetch_form"):
            if st.session_state.fetch_mode == "Single":
                st.session_state.single_reg_no = st.number_input("College Roll Number OD", min_value=1, value=1230121001, step=1)
            else:
                st.session_state.start_reg_no = st.number_input("Start College Roll Number OD", min_value=1, value=1230121001, step=1)
                st.session_state.end_reg_no = st.number_input("End College Roll Number OD", min_value=1, value=1230121078, step=1)

            submitted = st.form_submit_button("Fetch data")
            if submitted:
                try:
                    with st.spinner("Fetching student data..."):
                        run_fetch()
                    st.success(f"Fetched {len(st.session_state.fetched_students)} record(s).")
                except Exception as exc:
                    st.error(str(exc))

        st.divider()
        st.header("Detail Access")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        unlock_col, lock_col = st.columns(2)
        if unlock_col.button("Unlock"):
            if password == DETAIL_PASSWORD:
                st.session_state.detail_unlocked = True
                st.session_state.detail_error = ""
            else:
                st.session_state.detail_error = "Wrong password"
                st.session_state.detail_unlocked = False
        if lock_col.button("Lock"):
            st.session_state.detail_unlocked = False
        if st.session_state.detail_error:
            st.error(st.session_state.detail_error)
        if st.session_state.detail_unlocked:
            st.success("Detailed view unlocked")

        st.divider()
        search_query = st.text_input("Search fetched results", placeholder="Name, reg no, course...")
        expand_all = st.checkbox("Expand all student records", value=False)
        st.caption("Flow: choose mode -> enter roll number(s) -> fetch -> search -> optionally unlock details.")

    students = filter_students(st.session_state.fetched_students, search_query)

    if not st.session_state.has_fetched:
        st.info("Fetch data from the sidebar to begin.")
        return

    if not students:
        st.info("No students matched the current search.")
        if st.session_state.fetch_failures:
            st.warning("Some requests failed.")
        return

    st.subheader("Fetched Results")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Loaded", len(st.session_state.fetched_students))
    col2.metric("Visible", len(students))
    col3.metric("Failures", len(st.session_state.fetch_failures))
    col4.metric("Detail", "Unlocked" if st.session_state.detail_unlocked else "Locked")

    if st.session_state.fetch_failures:
        with st.expander("Fetch failures", expanded=False):
            for failure in st.session_state.fetch_failures:
                st.markdown(f"- `{failure['regNo']}`: {failure['error']}")

    download_col1, download_col2, download_col3, download_col4 = st.columns(4)
    download_col1.download_button(
        "Download basic CSV",
        data=basic_csv_bytes(st.session_state.fetched_students),
        file_name="students_basic.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download_col2.download_button(
        "Download basic HTML",
        data=basic_html(st.session_state.fetched_students).encode("utf-8"),
        file_name="students_basic.html",
        mime="text/html",
        use_container_width=True,
    )
    if st.session_state.detail_unlocked:
        download_col3.download_button(
            "Download detailed ZIP",
            data=detailed_zip_bytes(st.session_state.fetched_students),
            file_name="students_detailed.zip",
            mime="application/zip",
            use_container_width=True,
        )
    else:
        download_col3.button("Download detailed ZIP", disabled=True, use_container_width=True)

    selected_label_list = [f"{student.get('regNo') or '-'} | {student.get('name') or '-'}" for student in students]
    st.session_state.selected_index = min(st.session_state.selected_index, max(len(selected_label_list) - 1, 0))
    selected_index = st.selectbox(
        "Select a student for detailed view",
        options=list(range(len(students))),
        format_func=lambda index: selected_label_list[index],
        index=st.session_state.selected_index,
    )
    st.session_state.selected_index = selected_index

    selected_student = students[selected_index]

    if st.session_state.detail_unlocked:
        detailed_json_bytes = json.dumps(selected_student, indent=4, ensure_ascii=False).encode("utf-8")
        download_col3.download_button(
            "Download detailed JSON",
            data=json.dumps(st.session_state.fetched_students, indent=4, ensure_ascii=False).encode("utf-8"),
            file_name="students_detailed.json",
            mime="application/json",
            use_container_width=True,
        )
        download_col4.download_button(
            "Download detailed HTML",
            data=detailed_html_report(st.session_state.fetched_students, unlocked=True).encode("utf-8"),
            file_name="students_detailed.html",
            mime="text/html",
            use_container_width=True,
        )
    else:
        download_col4.button("Download detailed HTML", disabled=True, use_container_width=True)

    st.markdown("---")
    for student in students:
        with st.expander(f"{student.get('regNo') or '-'} - {student.get('name') or '-'}", expanded=expand_all):
            render_basic_card(student)

    st.markdown("---")
    show_selected_detail = st.checkbox("Show selected student detail", value=False)
    if show_selected_detail:
        render_detail_view(selected_student, st.session_state.detail_unlocked)


if __name__ == "__main__":
    main()
