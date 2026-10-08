#!/usr/bin/env python3
"""Clone the template, solution and tests repositories of an Artemis programming
exercise, save its problem statement, and update the Gradle wrapper,
dependencies and Java version.

Usage:
    ./artemis_clone_exercise.py https://artemis.tum.de/course-management/590/programming-exercises/21645

Credentials come from --username / $ARTEMIS_USERNAME and $ARTEMIS_PASSWORD or
are prompted for. The minted VCS tokens are stored in the cloned repositories'
.git/config files (as with repositories cloned through the Artemis UI).
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "artemis-clone-exercise/2.0"
REPO_TYPES = ("TEMPLATE", "SOLUTION", "TESTS")
EXERCISE_ID_RE = re.compile(r"/(?:programming-exercises|exercises)/(\d+)(?=[/?#]|$)")

JAVA_VERSION = "25"
DEPENDENCY_VERSIONS = {
    "org.apache.commons:commons-lang3": "3.21.0",
    "org.checkerframework:checker-qual": "4.3.0",
    "org.checkerframework:checker": "4.3.0",
    "org.easymock:easymock": "5.7.0",
    "org.aspectj:aspectjrt": "1.9.25.1",
    "de.tum.cit.ase:eos": "1.1.0",
    "org.assertj:assertj-core": "3.27.7",
    "com.tngtech.archunit:archunit": "1.5.1",
    "com.github.javaparser:javaparser-core": "3.28.2",
    "net.bytebuddy:byte-buddy": "1.18.14",
    "net.bytebuddy:byte-buddy-agent": "1.18.14",
    "org.ow2.asm:asm": "9.10.1",
    "org.ow2.asm:asm-tree": "9.10.1",
    "org.junit.jupiter:junit-jupiter": "6.1.3",
    "org.junit.platform:junit-platform-launcher": "6.1.3",
    "org.mockito:mockito-core": "5.24.0",
    "org.mockito:mockito-junit-jupiter": "5.24.0",
    "org.testfx:openjfx-monocle": "21.0.2",
}
PLUGIN_VERSIONS = {"io.freefair.aspectj.post-compile-weaving": "9.8.0"}


def api(base, path, jwt=None, data=None, method=None):
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    body = json.dumps(data).encode() if data is not None else None
    if body:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    if jwt:
        request.add_header("Authorization", f"Bearer {jwt}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise SystemExit(f"Network error: {error.reason}")


def redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def clone(name, uri, login, repo_token, target, secrets):
    if os.path.isdir(os.path.join(target, ".git")):
        print(f"  {name}: already cloned at {target}")
        return True
    if os.path.exists(target):
        raise SystemExit(f"{target} exists but is not a git repository.")
    parts = urllib.parse.urlsplit(uri)
    auth_uri = urllib.parse.urlunsplit((parts.scheme, f"{login}:{repo_token}@{parts.hostname}", parts.path, "", ""))
    process = subprocess.run(
        ["git", "clone", auth_uri, target], capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )
    if process.returncode:
        print(f"  {name}: clone failed.", file=sys.stderr)
        if process.stderr.strip():
            print("    " + redact(process.stderr.strip(), secrets).replace("\n", "\n    "), file=sys.stderr)
        shutil.rmtree(target, ignore_errors=True)
        return False
    print(f"  {name}: cloned to {target}")
    return True


def normalize_java_blocks(text):
    compat = re.compile(r"^\s*(?:sourceCompatibility|targetCompatibility)\s*=\s*(?:JavaVersion\.VERSION_\d+|['\"]\d+['\"])\s*$")
    lines = text.splitlines()
    result = []
    index = 0
    while index < len(lines):
        if re.match(r"\s*java\s*\{", lines[index]):
            depth = lines[index].count("{") - lines[index].count("}")
            block = [lines[index]]
            end = index + 1
            while end < len(lines) and depth > 0:
                block.append(lines[end])
                depth += lines[end].count("{") - lines[end].count("}")
                end += 1
            if depth == 0 and any(compat.match(line) for line in block):
                indent = re.match(r"\s*", block[0]).group()
                body = [line for line in block[1:-1] if not compat.match(line)]
                if not any(line.strip().startswith("toolchain") for line in body):
                    body.extend(
                        [
                            f"{indent}    toolchain {{",
                            f"{indent}        languageVersion = JavaLanguageVersion.of({JAVA_VERSION})",
                            f"{indent}    }}",
                        ]
                    )
                result.append(block[0])
                result.extend(body)
                result.append(block[-1])
                index = end
                continue
        result.append(lines[index])
        index += 1
    leftover = [position for position, line in enumerate(result) if compat.match(line)]
    if leftover:
        indent = re.match(r"\s*", result[leftover[0]]).group()
        for position in reversed(leftover[1:]):
            del result[position]
        result[leftover[0] : leftover[0] + 1] = [
            f"{indent}java {{",
            f"{indent}    toolchain {{",
            f"{indent}        languageVersion = JavaLanguageVersion.of({JAVA_VERSION})",
            f"{indent}    }}",
            f"{indent}}}",
        ]
    return "\n".join(result) + ("\n" if text.endswith("\n") else "")


def update_build_text(text):
    for coordinate, version in DEPENDENCY_VERSIONS.items():
        text = re.sub(rf"({re.escape(coordinate)}):[^\s:'\"\)\],]+", rf"\g<1>:{version}", text)
    for plugin, version in PLUGIN_VERSIONS.items():
        text = re.sub(
            rf"(id\s*\(?\s*['\"]{re.escape(plugin)}['\"]\s*\)?\s+version\s+['\"])[^'\"]+(['\"])",
            rf"\g<1>{version}\g<2>",
            text,
        )
    text = re.sub(r"JavaLanguageVersion\.of\(\s*\d+\s*\)", f"JavaLanguageVersion.of({JAVA_VERSION})", text)
    return normalize_java_blocks(text)


def update_build_files(repo_dir):
    changed = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [name for name in dirs if name not in (".git", ".gradle")]
        for filename in files:
            if not filename.endswith((".gradle", ".gradle.kts")):
                continue
            path = os.path.join(root, filename)
            with open(path, encoding="utf-8") as handle:
                original = handle.read()
            updated = update_build_text(original)
            if updated != original:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(updated)
                changed.append(os.path.relpath(path, repo_dir))
    if changed:
        print(f"  updated dependencies/Java in: {', '.join(changed)}")


def update_gradle(repo_dir, version):
    gradlew = os.path.abspath(os.path.join(repo_dir, "gradlew"))
    if not os.path.isfile(gradlew):
        print("  no gradlew found, skipping Gradle update.", file=sys.stderr)
        return
    os.chmod(gradlew, 0o755)
    for attempt in range(2):
        note = "" if attempt == 0 else " (fetching new distribution)"
        print(f"  ./gradlew wrapper --gradle-version {version}{note}")
        process = subprocess.run(
            [gradlew, "--no-daemon", "--console=plain", "wrapper", "--gradle-version", version],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if process.returncode:
            print("  WARNING: Gradle wrapper update failed.", file=sys.stderr)
            output = (process.stdout + process.stderr).strip()
            if output:
                print("    " + output.replace("\n", "\n    "), file=sys.stderr)
            return
    print(f"  Gradle wrapper updated to {version}")


def main():
    parser = argparse.ArgumentParser(description="Clone the template/solution/tests repositories of an Artemis exercise and update their Gradle wrapper.")
    parser.add_argument("url", nargs="?", help="Artemis exercise URL (prompted if omitted)")
    parser.add_argument("--dir", help="target directory (default: lower-cased project key)")
    parser.add_argument("--gradle-version", default="9.8.0", help="Gradle wrapper version (default: %(default)s)")
    parser.add_argument("--no-gradle", action="store_true", help="only clone, do not update dependencies or the Gradle wrapper")
    parser.add_argument("--username", default=os.environ.get("ARTEMIS_USERNAME"), help="Artemis login (default: $ARTEMIS_USERNAME or prompt)")
    args = parser.parse_args()

    url = args.url or input("Artemis exercise URL: ").strip()
    match = EXERCISE_ID_RE.search(url)
    if not match:
        raise SystemExit("Expected an Artemis URL containing .../programming-exercises/<id>.")
    exercise_id = int(match.group(1))
    base = f"https://{urllib.parse.urlsplit(url).hostname}"

    username = args.username or input("Artemis / TUM username: ").strip()
    password = os.environ.get("ARTEMIS_PASSWORD") or getpass.getpass("Password: ")

    print("Authenticating ...")
    status, body = api(base, "/api/core/public/authenticate", data={"username": username, "password": password}, method="POST")
    try:
        jwt = json.loads(body).get("access_token")
    except (json.JSONDecodeError, AttributeError):
        jwt = None
    if not jwt:
        raise SystemExit(f"Authentication failed (HTTP {status}).")
    secrets = [password, jwt]

    status, body = api(base, f"/api/programming/programming-exercises/{exercise_id}/with-template-and-solution-participation", jwt=jwt)
    if status != 200:
        raise SystemExit(f"Could not fetch exercise {exercise_id} (HTTP {status}); are you at least a tutor in its course?")
    exercise = json.loads(body)
    project_key = exercise.get("projectKey") or f"exercise-{exercise_id}"
    print(f"Exercise: {exercise.get('title')} (project key {project_key})")
    uris = {
        "TEMPLATE": exercise["templateParticipation"]["repositoryUri"],
        "SOLUTION": exercise["solutionParticipation"]["repositoryUri"],
        "TESTS": exercise.get("testRepositoryUri") or re.sub(r"-(?:exercise|solution)\.git$", "-tests.git", exercise["templateParticipation"]["repositoryUri"]),
    }

    target_root = args.dir or project_key.lower()
    statement = (exercise.get("problemStatement") or "").strip()
    if statement:
        os.makedirs(target_root, exist_ok=True)
        statement_path = os.path.join(target_root, "problem_statement.md")
        with open(statement_path, "w", encoding="utf-8") as handle:
            handle.write(statement + "\n")
        print(f"Problem statement saved to {statement_path}")
    else:
        print("WARNING: exercise has no problem statement.", file=sys.stderr)

    print(f"Cloning into {target_root}/ ...")
    for kind in REPO_TYPES:
        uri = uris[kind]
        name = uri.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        target = os.path.join(target_root, name)
        status, body = api(base, f"/api/programming/repository-vcs-access-token?exerciseId={exercise_id}&repositoryType={kind}", jwt=jwt, method="PUT")
        repo_token = body.decode().strip().strip('"') if status == 200 else ""
        if not repo_token:
            raise SystemExit(f"Could not obtain a VCS access token for the {kind} repository (HTTP {status}); tutor rights are required.")
        secrets.append(repo_token)
        if clone(name, uri, username, repo_token, target, secrets) and not args.no_gradle:
            update_build_files(target)
            update_gradle(target, args.gradle_version)

    print("Done.")


if __name__ == "__main__":
    main()
