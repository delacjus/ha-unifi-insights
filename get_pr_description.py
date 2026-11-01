import re

with open("pr_description.md", "r") as f:
    body = f.read()

def escapeRegExp(value):
  return re.sub(r'[.*+?^${}()|[\]\\]', r'\\\g<0>', value)

def stripHtmlComments(text):
  return re.sub(r'<!--[\s\S]*?-->', '', text or "").strip()

def getSection(sectionTitle):
  pattern = re.compile(
    rf'##\s*{escapeRegExp(sectionTitle)}\s*\r?\n([\s\S]*?)(?=\r?\n##\s|$)',
    re.IGNORECASE,
  )
  match = pattern.search(body)
  return match.group(1).strip() if match else ""

related_issues = getSection("Related Issues")
print(f"Related issues raw: {related_issues}")

relatedIssuesClean = stripHtmlComments(related_issues)

isExplicitNone = re.search(r'^(?:none|n\/a|not applicable|no issue|standalone)\b', relatedIssuesClean, re.IGNORECASE)
print(f"Is explicit none: {isExplicitNone}")
