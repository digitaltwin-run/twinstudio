#!/usr/bin/env python3
"""Verify that TwinStudio loads a project and parses visible 3D geometry in a real browser."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--screenshot", type=Path, default=Path("/tmp/twinstudio-ui.png"))
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    args = parser.parse_args()

    executable = next(
        (path for name in ("google-chrome", "chromium", "chromium-browser") if (path := shutil.which(name))),
        None,
    )
    console_errors: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(
                {"text": message.text, "url": str(message.location.get("url", ""))}
            )
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(f"{request.url}: {request.failure}"),
        )
        response = page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        assert response is not None and response.ok, f"UI HTTP status: {response.status if response else 'none'}"
        page.wait_for_function(
            "document.querySelector('#viewer3d')?.dataset.viewerState === 'ready'",
            timeout=args.timeout_ms,
        )

        project_options = page.locator("#projectSelect option").all_text_contents()
        project_id = page.locator("#projectSelect").input_value()
        tree_rows = page.locator("#objectTree .tree-row").count()
        viewer = page.locator("#viewer3d")
        loaded_meshes = int(viewer.get_attribute("data-loaded-meshes") or 0)
        expected_meshes = int(viewer.get_attribute("data-expected-meshes") or 0)
        triangles = int(viewer.get_attribute("data-rendered-triangles") or 0)
        webgl_canvas = page.locator("#viewer3d canvas").first
        canvas_box = webgl_canvas.bounding_box()
        context_response = page.request.get(f"{args.url}/api/v1/projects/{project_id}/ui-context")
        context = context_response.json()

        assert project_id, "No project selected"
        assert project_options and "Raspberry Pi 5" in project_options[0], project_options
        assert tree_rows > 0, "Product tree is empty"
        assert expected_meshes >= 1, "Project declares no viewer meshes"
        assert loaded_meshes == expected_meshes, (loaded_meshes, expected_meshes)
        assert triangles > 0, "STL files were not parsed into triangles"
        assert canvas_box and canvas_box["width"] > 100 and canvas_box["height"] > 100, canvas_box
        assert context_response.ok, context_response.text()
        assert context["viewer_state"] == "ready", context
        assert context["loaded_mesh_count"] == loaded_meshes, context
        assert all(item["status"] == "visible" for item in context["artifacts"]), context["artifacts"]
        relevant_console_errors = [item for item in console_errors if not item["url"].endswith("/favicon.ico")]
        assert not relevant_console_errors, relevant_console_errors
        assert not page_errors, page_errors
        assert not failed_requests, failed_requests

        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.screenshot), full_page=True)
        report = {
            "status": "ok",
            "url": args.url,
            "project_id": project_id,
            "project_options": project_options,
            "tree_rows": tree_rows,
            "loaded_meshes": loaded_meshes,
            "expected_meshes": expected_meshes,
            "rendered_triangles": triangles,
            "visible_artifact_uris": context["visible_artifact_uris"],
            "screenshot": str(args.screenshot),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
