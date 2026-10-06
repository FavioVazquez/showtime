---
type: regex
target: last_message
flags: i
pattern: 'select[\s\S]+sum\s*\(\s*(?:\w+\.)?amount\s*\)[\s\S]+order\s+by[\s\S]+(?:limit\s+5|fetch\s+first\s+5|top\s*\(?\s*5)'
---
