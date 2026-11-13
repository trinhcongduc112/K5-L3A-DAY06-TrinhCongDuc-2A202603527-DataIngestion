"""Build a cleaned Kubernetes-docs corpus + manifest.

Usage: python3 -I build_corpus.py <repo_dir> <out_dir> <commit> <accessed_at>
"""
import csv, json, os, re, subprocess, sys

repo, out, commit, accessed = sys.argv[1:5]
BASE = os.path.join(repo, "content/en/docs/concepts")
SECTIONS = {"workloads": "Workloads", "services-networking": "Services, Load Balancing, and Networking"}
MIN_CHARS = 1500           # below this a page is treated as a stub / nav page
CHARS_PER_PRINTED_PAGE = 3000

def clean(text):
    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"\'')
        text = text[m.end():]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\{<\s*glossary_tooltip[^>]*text=\"([^\"]+)\"[^>]*>\}\}", r"\1", text)
    text = re.sub(r"\{\{<\s*glossary_tooltip[^>]*term_id=\"([^\"]+)\"[^>]*>\}\}", r"\1", text)
    text = re.sub(r"\{\{[<%].*?[>%]\}\}", "", text, flags=re.S)   # remaining shortcodes
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # links -> anchor text
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return fm, text

os.makedirs(os.path.join(out, "pages"), exist_ok=True)
rows = []
for sec, sec_title in SECTIONS.items():
    for root, _, files in os.walk(os.path.join(BASE, sec)):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, os.path.join(repo, "content/en"))
            fm, body = clean(open(path, encoding="utf-8").read())
            n = len(body)
            if f == "_index.md" or n < MIN_CHARS:
                continue
            slug = os.path.splitext(os.path.relpath(path, BASE))[0]
            url = "https://kubernetes.io/" + rel[:-3] + "/"
            sid = "k8s-" + slug.replace("/", "-")
            subsec = os.path.relpath(root, os.path.join(BASE, sec)).replace(".", "") or "(root)"
            with open(os.path.join(out, "pages", sid + ".md"), "w", encoding="utf-8") as fo:
                fo.write(body)
            rows.append({
                "source_id": sid,
                "title": fm.get("title", slug),
                "section": sec,
                "subsection": subsec,
                "source_url": url,
                "source_repo_path": f"kubernetes/website@{commit[:12]}:content/en/{rel}",
                "github_permalink": f"https://github.com/kubernetes/website/blob/{commit}/content/en/{rel}",
                "git_blob_sha1": subprocess.run(["git", "-C", repo, "hash-object", os.path.abspath(path)], capture_output=True, text=True).stdout.strip(),
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "© The Kubernetes Authors, Kubernetes Documentation",
                "accessed_at": accessed,
                "char_count": n,
                "approx_printed_pages": round(n / CHARS_PER_PRINTED_PAGE, 1),
            })

rows.sort(key=lambda r: (r["section"], r["subsection"], r["source_id"]))
fields = list(rows[0].keys())
with open(os.path.join(out, "manifest.csv"), "w", newline="", encoding="utf-8") as fo:
    w = csv.DictWriter(fo, fieldnames=fields); w.writeheader(); w.writerows(rows)

summary = {}
for r in rows:
    s = summary.setdefault(r["section"], {"pages": 0, "chars": 0})
    s["pages"] += 1; s["chars"] += r["char_count"]
total_chars = sum(r["char_count"] for r in rows)
manifest = {
    "corpus_name": "Kubernetes Concepts — Workloads & Networking",
    "publisher": "The Kubernetes Authors (CNCF / Linux Foundation)",
    "source": "https://github.com/kubernetes/website (rendered at https://kubernetes.io/docs/concepts/)",
    "commit": commit,
    "license": "CC BY 4.0 (documentation); code samples in the repo are Apache-2.0",
    "accessed_at": accessed,
    "metadata_filter_fields": ["section", "subsection"],
    "inclusion_rule": f"English concept pages under the two sections; _index.md and pages < {MIN_CHARS} chars after cleaning excluded",
    "cleaning": "front matter, HTML comments and Hugo shortcodes removed; links reduced to anchor text; code blocks kept",
    "totals": {"pages": len(rows), "chars": total_chars,
               "approx_printed_pages": round(total_chars / CHARS_PER_PRINTED_PAGE, 1),
               "by_section": summary},
    "documents": rows,
}
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps(manifest["totals"], indent=2))
for r in rows:
    print(f'{r["section"][:8]:8} {r["subsection"]:12} {r["char_count"]:6}  {r["title"]}')
