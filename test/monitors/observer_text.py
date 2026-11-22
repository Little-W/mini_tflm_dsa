# SPDX-License-Identifier: Apache-2.0
"""在生产宏定义下启用观察模块，并保留其他条件编译分支。"""
import re


def simulation_text(content: str) -> str:
    directives = list(re.finditer(
        r"^[ \t]*`(ifdef|ifndef|endif|else|elsif)\b[^\n]*(?:\n|$)",
        content, flags=re.M))
    opening = next((index for index, directive in enumerate(directives)
                    if re.fullmatch(r"[ \t]*`ifndef[ \t]+SYNTHESIS[ \t]*(?:\n)?",
                                    directive.group())), None)
    if opening is None:
        raise ValueError("Observer requires an explicit SYNTHESIS guard")
    depth = 0
    for directive in directives[opening:]:
        operation = directive.group(1)
        if operation in ("ifdef", "ifndef"):
            depth += 1
        elif operation == "endif":
            depth -= 1
            if depth == 0:
                start = directives[opening]
                return (content[:start.start()] + "\n" +
                        content[start.end():directive.start()] + "\n" +
                        content[directive.end():])
        elif depth == 1:
            raise ValueError("Observer SYNTHESIS guard must contain one simulation branch")
    raise ValueError("Observer SYNTHESIS guard is unterminated")
