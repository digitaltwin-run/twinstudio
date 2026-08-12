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
        automatic_note_verified = False
        undo_verified = False
        queue_tree_marker_verified = False
        queue_screenshot = None
        previous_height = None
        automatic_height = None
        if args.verify_plan:
            page.locator("#changePrompt").fill("zmniejsz o 4mm")
            page.locator("#planButton").click()
            page.locator("#planContent .plan-op").first.wait_for(timeout=args.timeout_ms)
            assert "selection=resolved" in page.locator("#plannerMode").inner_text()
            assert "Planner lokalny" in page.locator("#plannerRuntime").inner_text()
            assert "Plan gotowy" in page.locator("#plannerProgress").inner_text()
            assert "Odświeżenie strony nie jest potrzebne" in page.locator(
                "#plannerProgress"
            ).inner_text()
            plan_content = page.locator("#planContent").inner_text().lower()
            assert "ten plan nie zmieni bryły" in plan_content
            assert "odświeżenie niczego nie zmieni" in plan_content
            assert page.locator("#applyButton").is_disabled()
            assert "Brak zmian" in page.locator("#applyButton").inner_text()
            assert "Brak zaznaczenia" not in page.locator("#banner").inner_text()
            queued_ambiguous = page.locator(
                '#changeQueue .queue-task[data-status="needs_detail"]'
            ).filter(has_text="zmniejsz o 4mm")
            queued_ambiguous.first.wait_for(timeout=args.timeout_ms)
            assert queued_ambiguous.first.locator("[data-open-plan]").is_visible()
            assert int(page.locator("#changeQueueCount").inner_text()) >= 1
            selected_task_marker = page.locator(
                '#objectTree .tree-row.selected .task-pill[data-status="needs_detail"]'
            )
            selected_task_marker.wait_for(timeout=args.timeout_ms)
            queue_tree_marker_verified = True
            queue_screenshot = args.screenshot.with_name(
                f"{args.screenshot.stem}-queue{args.screenshot.suffix}"
            )
            page.screenshot(path=str(queue_screenshot), full_page=True)
            plan_verified = True
            project_before = page.request.get(
                f"{args.url}/api/v1/projects/{project_id}"
            ).json()["project"]
            base_uri = "poa://demo/demo-rpi5@main/part/base"
            previous_height = float(
                project_before["objects"][base_uri]["parameters"]["height"]["value"]
            )
            automatic_height = previous_height - 4
            page.locator("#annotationText").fill("zmniejsz wysokosc o 4mm")
            page.locator("#saveAnnotation").click()
            page.wait_for_function(
                "document.querySelector('#applyStatus')?.textContent.includes('Uwaga wykonana automatycznie')",
                timeout=args.timeout_ms,
            )
            page.locator("#changeHistory [data-undo-event]").first.wait_for(
                timeout=args.timeout_ms
            )
            project_after_apply = page.request.get(
                f"{args.url}/api/v1/projects/{project_id}"
            ).json()["project"]
            assert (
                float(
                    project_after_apply["objects"][base_uri]["parameters"]["height"][
                        "value"
                    ]
                )
                == automatic_height
            )
            automatic_note_verified = True
            page.locator("#changeHistory [data-undo-event]").first.click()
            page.wait_for_function(
                "document.querySelector('#changeHistory')?.textContent.includes('Cofnięcie zmiany')",
                timeout=args.timeout_ms,
            )
            page.wait_for_function(
                """async expected => {
                    const projectId = document.querySelector('#projectSelect').value;
                    const response = await fetch(`/api/v1/projects/${projectId}`);
                    if (!response.ok) return false;
                    const project = (await response.json()).project;
                    return Number(project.objects['poa://demo/demo-rpi5@main/part/base']
                        .parameters.height.value) === expected;
                }""",
                arg=previous_height,
                timeout=args.timeout_ms,
            )
            page.wait_for_function(
                "[...new URL(location.href).searchParams.getAll('args')]"
                ".some(item => item.includes('|change.undo.completed|'))",
                timeout=args.timeout_ms,
            )
            undo_verified = True
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
        if args.verify_plan:
            assert any("|plan.requested|" in item for item in action_args), action_args
            assert any("|plan.completed|" in item for item in action_args), action_args
            assert any("|plan.apply.completed|" in item for item in action_args), action_args
            assert any("|change.undo.completed|" in item for item in action_args), action_args
        projection_actions = [
            item for item in action_args if "|viewer2d.projection.ready|" in item
        ]
        assert projection_actions, action_args
        if args.simulate_legacy_svg_cache:
            assert any("source=polygon-order-fallback" in item for item in projection_actions)
        assert "?args=" in final_context["route"], final_context["route"]
        selected_tree_row = page.locator("#objectTree .tree-row.selected").first
        selected_tree_row.click()
        page.wait_for_function(
            "document.querySelector('#viewer3d')?.dataset.highlightedMeshes === '1'",
            timeout=args.timeout_ms,
        )
        page.wait_for_function(
            """[...document.querySelectorAll('.object-highlight-overlay')].length === 3
                && [...document.querySelectorAll('.object-highlight-overlay')]
                    .every(canvas => Number(canvas.dataset.highlightRegions) === 1)""",
            timeout=args.timeout_ms,
        )
        assert (page.locator("#viewer3d").get_attribute("data-highlighted-object") or "").endswith(
            "/part/base"
        )
        assert page.locator('.drawing-card[data-object-highlight="mapped"]').count() == 3
        tree_highlight_args = page.evaluate(
            "[...new URL(location.href).searchParams.getAll('args')]"
        )
        assert any("|object.selected|" in item and "highlight3d=1" in item for item in tree_highlight_args)
        page.locator("#objectTree .tree-row").filter(has_text="Upper lid").click()
        page.wait_for_function(
            "document.querySelector('#objectTree .tree-row.selected')?.textContent.includes('Upper lid')"
            " && document.querySelector('#selectionSummary')?.textContent.includes('Wybór z drzewa')",
            timeout=args.timeout_ms,
        )
        assert "front.base.outer-wall" not in page.locator("#selectionSummary").inner_text()
        unrelated_switch_args = page.evaluate(
            "[...new URL(location.href).searchParams.getAll('args')]"
        )
        assert any(
            "|object.selected|" in item and "selection_reset=true" in item
            for item in unrelated_switch_args
        )
        page.locator("#objectTree .tree-row").filter(has_text="Lower base").click()
        tree_highlight_verified = True
        tab_pdf_bytes: dict[str, int] = {}
        tab_pdf_files: dict[str, str] = {}
        for tab in ("view3d", "view2d", "spec", "lifecycle", "tests", "fixation", "evolution"):
            page.locator(f'.tab[data-tab="{tab}"]').click()
            page.wait_for_function(
                "expected => document.querySelector('#downloadTabPdf')?.textContent.includes(expected)",
                arg={
                    "view3d": "3D",
                    "view2d": "2D",
                    "spec": "Specyfikacja / xBOM",
                    "lifecycle": "Lifecycle",
                    "tests": "Testy i symulacje",
                    "fixation": "Feature lenses",
                    "evolution": "Evolution / DSL",
                }[tab],
                timeout=args.timeout_ms,
            )
            with page.expect_download(timeout=args.timeout_ms) as download_info:
                page.locator("#downloadTabPdf").click()
            download = download_info.value
            destination = args.screenshot.with_name(
                f"{args.screenshot.stem}-{tab}{Path(download.suggested_filename).suffix}"
            )
            download.save_as(destination)
            content = destination.read_bytes()
            assert content.startswith(b"%PDF-"), (tab, destination)
            assert len(content) > 1_000, (tab, len(content))
            tab_pdf_bytes[tab] = len(content)
            tab_pdf_files[tab] = str(destination)
        pdf_action_args = page.evaluate(
            "[...new URL(location.href).searchParams.getAll('args')]"
        )
        for tab in tab_pdf_bytes:
            assert any(
                "|tab.pdf.requested|" in item and f"tab={tab}" in item
                for item in pdf_action_args
            ), (tab, pdf_action_args)
            assert any(
                "|tab.pdf.downloaded|" in item and f"tab={tab}" in item
                for item in pdf_action_args
            ), (tab, pdf_action_args)
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
        page.evaluate(
            """
            Object.defineProperty(navigator.clipboard, 'writeText', {
              configurable: true,
              value: async () => { throw new DOMException('test permission rejection', 'NotAllowedError'); },
            })
            """
        )
        page.locator("#copyDslLogs").click()
        page.wait_for_function(
            "document.querySelector('#banner').textContent.includes('tryb zgodności')",
            timeout=args.timeout_ms,
        )
        fallback_clipboard_dsl = page.evaluate("navigator.clipboard.readText()")
        assert 'KIND "UiAction"' in fallback_clipboard_dsl
        download_logs_href = page.locator("#downloadDslLogs").get_attribute("href")
        assert download_logs_href == f"/api/v1/projects/{project_id}/logs.dsl?limit=300"
        page.locator('.tab[data-tab="view2d"]').click()
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
            "tab_pdf_bytes": tab_pdf_bytes,
            "tab_pdf_files": tab_pdf_files,
            "drawing_selection": "ok",
            "drawing_selection_target": "part/base",
            "drawing_projection_entity": "front.base.outer-wall",
            "drawing_projection_loader": (
                "polygon-order-fallback"
                if args.simulate_legacy_svg_cache
                else "svg-metadata"
            ),
            "tree_selection_highlights_3d_and_2d": tree_highlight_verified,
            "plan_from_inferred_selection": plan_verified,
            "planner_runtime": page.locator("#plannerRuntime").inner_text(),
            "plan_changes_geometry": False if plan_verified else None,
            "plan_apply_available": (
                not page.locator("#applyButton").is_disabled() if plan_verified else None
            ),
            "automatic_note_execution": automatic_note_verified,
            "undo_from_change_history": undo_verified,
            "change_queue_tree_marker": queue_tree_marker_verified,
            "queue_screenshot": str(queue_screenshot) if queue_screenshot else None,
            "height_before": previous_height,
            "height_automatic": automatic_height,
            "url_action_args": len(action_args),
            "clipboard_dsl_characters": len(clipboard_dsl),
            "clipboard_fallback_verified": True,
            "download_logs_href": download_logs_href,
            "visible_artifact_uris": final_context["visible_artifact_uris"],
            "screenshot": str(args.screenshot),
            "drawings_screenshot": str(drawings_screenshot),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
