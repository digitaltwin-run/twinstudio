#!/usr/bin/env python3
"""Verify that TwinStudio loads a project and parses visible 3D geometry in a real browser."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--screenshot", type=Path, default=Path("/tmp/twinstudio-ui.png"))
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--verify-plan", action="store_true")
    parser.add_argument("--simulate-legacy-svg-cache", action="store_true")
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
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"],
        )
        if args.simulate_legacy_svg_cache:
            def serve_legacy_projection_svg(route) -> None:
                response = route.fetch()
                body = re.sub(
                    r' data-projection-entity="[^"]+" data-selection-bbox="[^"]+"',
                    "",
                    response.text(),
                )
                route.fulfill(response=response, body=body)

            context.route(
                re.compile(r".*/artifacts/assembly-front\?projection-regions=2$"),
                serve_legacy_projection_svg,
            )
        page = context.new_page()
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
        page.locator('.tab[data-tab="view2d"]').click()
        page.wait_for_function(
            "[...document.querySelectorAll('#drawingList img')].length > 0 && "
            "[...document.querySelectorAll('#drawingList img')].every(image => image.complete && image.naturalWidth > 0)",
            timeout=args.timeout_ms,
        )
        drawing_cards = page.locator("#drawingList .drawing-card").count()
        drawing_labels = page.locator("#drawingList .drawing-card h3").all_text_contents()
        drawing_canvases = page.locator("#drawingList .drawing-canvas").count()
        pdf_response = page.request.get(f"{args.url}/api/v1/projects/{project_id}/drawings.pdf")
        assert drawing_cards == 3, drawing_labels
        assert drawing_labels == ["Front", "Top", "Side"], drawing_labels
        assert drawing_canvases == drawing_cards
        assert page.locator("#drawingView").count() == 0
        assert pdf_response.ok and pdf_response.headers["content-type"] == "application/pdf"
        assert (await_pdf := pdf_response.body()).startswith(b"%PDF-") and len(await_pdf) > 2_000
        page.locator('.tool2d[data-tool="rectangle"]').click()
        drawing_canvas = page.locator(".drawing-canvas").first
        drawing_box = drawing_canvas.bounding_box()
        assert drawing_box, "Front drawing canvas has no layout box"
        page.mouse.move(
            drawing_box["x"] + drawing_box["width"] * 0.24,
            drawing_box["y"] + drawing_box["height"] * 0.50,
        )
        page.mouse.down()
        page.mouse.move(
            drawing_box["x"] + drawing_box["width"] * 0.76,
            drawing_box["y"] + drawing_box["height"] * 0.72,
            steps=5,
        )
        page.mouse.up()
        page.wait_for_function(
            "document.querySelector('#selectionSummary')?.textContent.includes('front.base.outer-wall')",
            timeout=args.timeout_ms,
        )
        selection_summary = page.locator("#selectionSummary").inner_text().lower()
        assert "2d" in selection_summary
        assert "part/base" in selection_summary
        assert "front.base.outer-wall" in selection_summary
        assert "Lower base" in page.locator("#objectTree .tree-row.selected").inner_text()
        plan_verified = False
        if args.verify_plan:
            page.locator("#changePrompt").fill("zmniejsz o 4mm")
            page.locator("#planButton").click()
            page.locator("#planContent .plan-op").first.wait_for(timeout=args.timeout_ms)
            assert "selection=resolved" in page.locator("#plannerMode").inner_text()
            assert "Brak zaznaczenia" not in page.locator("#banner").inner_text()
            plan_verified = True
        page.wait_for_function(
            """async expected => {
                const response = await fetch(`/api/v1/projects/${document.querySelector('#projectSelect').value}/ui-context`);
                if (!response.ok) return false;
                const context = await response.json();
                return context.visible_artifact_uris.length === expected
                    && context.artifacts.filter(item => item.status === 'visible').length === expected;
            }""",
            arg=loaded_meshes + drawing_cards,
            timeout=args.timeout_ms,
        )
        final_context_response = page.request.get(
            f"{args.url}/api/v1/projects/{project_id}/ui-context"
        )
        final_context = final_context_response.json()
        assert final_context_response.ok, final_context_response.text()
        assert len(final_context["visible_artifact_uris"]) == loaded_meshes + drawing_cards
        action_args = page.evaluate("[...new URL(location.href).searchParams.getAll('args')]")
        assert len(action_args) >= 4, action_args
        assert not any("|click|" in item and "tree-row" in item for item in action_args), action_args
        assert any("|selection.created|" in item for item in action_args), action_args
        assert any("|object.inferred|" in item for item in action_args), action_args
        projection_actions = [
            item for item in action_args if "|viewer2d.projection.ready|" in item
        ]
        assert projection_actions, action_args
        if args.simulate_legacy_svg_cache:
            assert any("source=polygon-order-fallback" in item for item in projection_actions)
        assert "?args=" in final_context["route"], final_context["route"]
        page.locator("#copyDslLogs").click()
        page.wait_for_function(
            "document.querySelector('#banner').textContent.includes('Skopiowano logi DSL')",
            timeout=args.timeout_ms,
        )
        clipboard_dsl = page.evaluate("navigator.clipboard.readText()")
        assert 'KIND "UiAction"' in clipboard_dsl
        assert 'CODE "UI_ACTION_RECORDED"' in clipboard_dsl
        assert "HTTP_REQUEST_COMPLETED" in clipboard_dsl
        assert "POSITION" in clipboard_dsl
        drawings_screenshot = args.screenshot.with_name(
            f"{args.screenshot.stem}-2d{args.screenshot.suffix}"
        )
        page.screenshot(path=str(drawings_screenshot), full_page=True)
        report = {
            "status": "ok",
            "url": args.url,
            "project_id": project_id,
            "project_options": project_options,
            "tree_rows": tree_rows,
            "loaded_meshes": loaded_meshes,
            "expected_meshes": expected_meshes,
            "rendered_triangles": triangles,
            "drawing_cards": drawing_cards,
            "drawing_labels": drawing_labels,
            "drawings_pdf_bytes": len(await_pdf),
            "drawing_selection": "ok",
            "drawing_selection_target": "part/base",
            "drawing_projection_entity": "front.base.outer-wall",
            "drawing_projection_loader": (
                "polygon-order-fallback"
                if args.simulate_legacy_svg_cache
                else "svg-metadata"
            ),
            "plan_from_inferred_selection": plan_verified,
            "url_action_args": len(action_args),
            "clipboard_dsl_characters": len(clipboard_dsl),
            "visible_artifact_uris": final_context["visible_artifact_uris"],
            "screenshot": str(args.screenshot),
            "drawings_screenshot": str(drawings_screenshot),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
