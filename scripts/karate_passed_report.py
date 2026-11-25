"""Filter an existing Karate v2 HTML report into a shareable ZIP."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryFile
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


SUMMARY_PAGE = "karate-summary.html"
REPORT_DATA = re.compile(
    r'(<script\b[^>]*\bid\s*=\s*["\']karate-data["\'][^>]*>)(.*?)(</script\s*>)',
    re.IGNORECASE | re.DOTALL,
)
TIMELINE_LINK = re.compile(
    r'<a\b[^>]*\shref=["\'](?:\./)?karate-timeline\.html["\'][^>]*>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)


@contextmanager
def report_source(path):
    if path.is_dir():
        root = path.resolve()
        names = [item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()]

        def open_file(name):
            file = (root / name).resolve()
            if not file.is_relative_to(root):
                raise ValueError(f"Report asset points outside the report folder: {name}")
            return file.open("rb")

        yield names, open_file
        return

    with ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        yield names, archive.open


def local_path(name):
    path = PurePosixPath(name)
    if (path.is_absolute() or not path.parts or ".." in path.parts
            or "\\" in name or ":" in name or "\x00" in name):
        raise ValueError(f"Unsupported report path: {name!r}")
    return path.as_posix()


def read_html(open_file, name):
    try:
        with open_file(name) as handle:
            html = handle.read().decode("utf-8")
    except (KeyError, FileNotFoundError) as error:
        raise ValueError(f"Missing report file: {name}. Supply the entire report folder.") from error
    match = REPORT_DATA.search(html)
    if not match:
        raise ValueError(f"{name} is missing embedded Karate v2 report data.")
    try:
        payload = json.loads(match[2])
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} contains invalid Karate report JSON.") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{name} contains unsupported Karate report data.")
    return html, payload


def write_html(html, payload, label):
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", r"\u003c")
    html = REPORT_DATA.sub(lambda match: match[1] + serialized + match[3], html, count=1)
    return re.sub(
        r"(<h1\b[^>]*>.*?</h1>)",
        lambda match: match[1] + f'<p class="my-2 text-sm font-semibold">{label}</p>',
        html, count=1, flags=re.IGNORECASE | re.DOTALL,
    )


def embedded_assets(value):
    if isinstance(value, list):
        for item in value:
            yield from embedded_assets(item)
    elif isinstance(value, dict):
        parts = value.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict) or "mime" not in part:
                    continue
                if part.get("file"):
                    yield "embeds/" + local_path(part["file"])
                elif part.get("url"):
                    url = urlsplit(part["url"])
                    if not url.scheme and not url.netloc:
                        yield local_path(unquote(url.path))
        for item in value.values():
            yield from embedded_assets(item)


def build_report(names, open_file, output):
    summaries = [name for name in names if PurePosixPath(name).name == SUMMARY_PAGE]
    if len(summaries) != 1:
        raise ValueError(f"Provide exactly one report with a {SUMMARY_PAGE} page.")
    prefix = summaries[0].removesuffix(SUMMARY_PAGE)
    files = {}
    for name in names:
        if name.startswith(prefix):
            relative = local_path(name[len(prefix):])
            if relative in files:
                raise ValueError(f"Duplicate report file: {relative}")
            files[relative] = name

    summary_html, summary = read_html(open_file, summaries[0])
    if not isinstance(summary.get("features"), list) or not isinstance(summary.get("summary"), dict):
        raise ValueError("Expected a Karate v2 summary with embedded feature results.")

    passed = excluded = 0
    features = []
    assets = {name for name in files if name.startswith("res/")}
    for required in ("res/karate-report.js", "res/karate-report.css", "res/alpine.min.js"):
        if required not in assets:
            raise ValueError(f"Missing report asset: {required}. Supply the entire report folder.")

    for row in summary["features"]:
        filename = row.get("fileName") if isinstance(row, dict) else None
        if not isinstance(filename, str) or local_path(filename) != filename or "/" in filename:
            raise ValueError("A feature in the summary has an invalid report filename.")
        relative = f"feature-html/{filename}.html"
        html, feature = read_html(open_file, files.get(relative, prefix + relative))
        scenarios = feature.get("scenarios")
        if not isinstance(scenarios, list):
            raise ValueError(f"{relative} is missing its scenario results.")
        if any(not isinstance(item, dict) or not isinstance(item.get("passed"), bool) for item in scenarios):
            raise ValueError(f"{relative} contains a scenario without a Karate pass/fail status.")
        retained = [item for item in scenarios if item["passed"] and not item.get("skipped")]
        excluded += len(scenarios) - len(retained)
        if not retained:
            continue

        count = len(retained)
        passed += count
        duration = sum(item.get("durationMillis") or 0 for item in retained)
        feature.update(scenarios=retained, passed=True, durationMillis=duration)
        feature.pop("failed", None)
        assets.update(embedded_assets(retained))
        output.writestr(relative, write_html(html, feature, "Passed-only report"))
        features.append({
            "name": row.get("name"),
            "relativePath": row.get("relativePath"),
            "fileName": filename,
            "passed": True,
            "failed": False,
            "durationMillis": duration,
            "scenarioCount": count,
            "passedCount": count,
            "failedCount": 0,
            "skippedCount": 0,
            "passedRate": 100,
            "scenarios": [
                {key: item.get(key) for key in ("name", "refId", "passed", "skipped", "durationMillis", "tags")}
                for item in retained
            ],
        })

    filtered_summary = {key: summary[key] for key in ("env", "reportDate", "karateVersion", "threads") if key in summary}
    filtered_summary.update(features=features, summary={
        "feature_count": len(features),
        "feature_passed": len(features),
        "feature_failed": 0,
        "scenario_count": passed,
        "scenario_passed": passed,
        "scenario_failed": 0,
        "scenario_skipped": 0,
        "duration_millis": sum(feature["durationMillis"] for feature in features),
        "status": "passed" if passed else "skipped",
    })
    label = f"Passed-only report · {excluded} non-passing scenarios excluded."
    summary_html = TIMELINE_LINK.sub("", summary_html)
    output.writestr(SUMMARY_PAGE, write_html(summary_html, filtered_summary, label))
    for asset in sorted(assets):
        if asset not in files:
            raise ValueError(f"Missing report asset: {asset}")
        with open_file(files[asset]) as source, output.open(asset, "w", force_zip64=True) as destination:
            shutil.copyfileobj(source, destination)

    return passed, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Karate v2 HTML report folder or ZIP")
    parser.add_argument("output", type=Path, help="Path for the new passed-only ZIP")
    args = parser.parse_args()
    try:
        with TemporaryFile() as staged:
            with report_source(args.report) as (names, open_file), ZipFile(staged, "w", ZIP_DEFLATED) as archive:
                passed, excluded = build_report(names, open_file, archive)
            staged.seek(0)
            with args.output.open("xb") as destination:
                try:
                    shutil.copyfileobj(staged, destination)
                except OSError:
                    destination.close()
                    args.output.unlink()
                    raise
    except (OSError, ValueError, BadZipFile) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"{args.output} · {passed} passed included, {excluded} non-passing excluded")


if __name__ == "__main__":
    main()
