import os
import unittest

from agent.dag_builder import build_dag, extract_resources
from agent.planner.action_step import ActionStep


class DagBuilderResourceTests(unittest.TestCase):
    def test_relative_read_after_write_creates_dependency_without_cwd_resolution(self):
        steps = [
            ActionStep(1, "python", "open('./reports/../output.txt', 'w')", "write"),
            ActionStep(2, "python", "open('output.txt', 'r')", "read"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[0].writes, ["file:output.txt"])
        self.assertEqual(dag[1].reads, ["file:output.txt"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_directory_creation_serializes_descendant_file_write(self):
        steps = [
            ActionStep(1, "python", "os.makedirs('reports', exist_ok=True)", "mkdir"),
            ActionStep(2, "python", "open('reports/result.txt', 'w')", "write"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[1].depends_on, [1])

    def test_directory_conflicts_ignore_case_without_rewriting_resources(self):
        steps = [
            ActionStep(1, "python", "os.makedirs('Reports', exist_ok=True)", "mkdir"),
            ActionStep(2, "python", "open('reports/result.txt', 'w')", "write"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[0].writes, ["file:Reports"])
        self.assertEqual(dag[1].writes, ["file:reports/result.txt"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_child_read_serializes_directory_removal(self):
        steps = [
            ActionStep(1, "python", "open('reports/result.txt', 'r')", "read"),
            ActionStep(2, "python", "shutil.rmtree('reports')", "remove"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[1].depends_on, [1])

    def test_sibling_file_writes_remain_parallel(self):
        steps = [
            ActionStep(1, "python", "open('reports/a.txt', 'w')", "write a"),
            ActionStep(2, "python", "open('reports/b.txt', 'w')", "write b"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[1].depends_on, [])

    def test_python_environment_path_references_create_dependency(self):
        steps = [
            ActionStep(
                1,
                "python",
                "open(os.getenv('REPORT_PATH'), 'w')",
                "write",
            ),
            ActionStep(
                2,
                "python",
                "open(os.environ['REPORT_PATH'], 'r')",
                "read",
            ),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[0].writes, ["file:envvar:REPORT_PATH"])
        self.assertEqual(dag[1].reads, ["file:envvar:REPORT_PATH"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_python_environment_path_defaults_are_inferred(self):
        steps = [
            ActionStep(1, "python", "open('fallback.txt', 'w')", "write"),
            ActionStep(
                2,
                "python",
                "open(os.getenv('REPORT_PATH', 'fallback.txt'), 'r')",
                "read",
            ),
        ]

        dag = build_dag(steps)

        self.assertEqual(
            dag[1].reads,
            ["file:envvar:REPORT_PATH", "file:fallback.txt"],
        )
        self.assertEqual(dag[1].depends_on, [1])

    def test_open_keyword_mode_and_encoding_are_parsed(self):
        steps = [
            ActionStep(
                1,
                "python",
                "open('shared.txt', encoding='utf8', mode='w')",
                "write",
            ),
            ActionStep(2, "python", "open('shared.txt', 'r')", "read"),
        ]

        dag = build_dag(steps)

        self.assertIn("file:shared.txt", dag[0].writes)
        self.assertEqual(dag[1].depends_on, [1])

    def test_open_file_keyword_is_inferred(self):
        steps = [
            ActionStep(1, "python", "open(file='keyword.txt', mode='w')", "write"),
            ActionStep(2, "python", "open('keyword.txt', 'r')", "read"),
        ]

        dag = build_dag(steps)

        self.assertIn("file:keyword.txt", dag[0].writes)
        self.assertEqual(dag[1].depends_on, [1])

    def test_dynamic_open_mode_is_not_assumed_to_be_read_only(self):
        reads, writes = extract_resources(
            "open('shared.txt', mode=output_mode)", "python"
        )

        self.assertEqual(reads, ["file:shared.txt"])
        self.assertEqual(writes, ["file:shared.txt"])

    def test_dynamic_path_expression_is_not_mistaken_for_its_literal_prefix(self):
        reads, writes = extract_resources("open('x' + suffix, 'w')", "python")

        self.assertEqual((reads, writes), ([], []))

    def test_relative_shutil_copy_and_move_paths_are_inferred(self):
        copy_reads, copy_writes = extract_resources(
            "shutil.copy('source.txt', 'copy.txt')", "python"
        )
        move_reads, move_writes = extract_resources(
            "shutil.move('source.txt', 'moved.txt')", "python"
        )

        self.assertIn("file:source.txt", copy_reads)
        self.assertIn("file:copy.txt", copy_writes)
        self.assertIn("file:source.txt", move_reads)
        self.assertIn("file:source.txt", move_writes)
        self.assertIn("file:moved.txt", move_writes)

    def test_shell_environment_path_references_create_dependency(self):
        steps = [
            ActionStep(1, "shell", "echo report > %REPORT_PATH%", "write"),
            ActionStep(2, "shell", "Get-Content $env:REPORT_PATH", "read"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[0].writes, ["file:envvar:REPORT_PATH"])
        self.assertEqual(dag[1].reads, ["file:envvar:REPORT_PATH"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_shell_environment_directory_paths_match_across_variable_syntax(self):
        steps = [
            ActionStep(
                1,
                "shell",
                'Set-Content -Path "$env:REPORT_DIR\\result.txt" -Value report',
                "write",
            ),
            ActionStep(2, "shell", "Get-Content %REPORT_DIR%/result.txt", "read"),
        ]

        dag = build_dag(steps)

        resource = "file:envvar:REPORT_DIR/result.txt"
        self.assertEqual(dag[0].writes, [resource])
        self.assertEqual(dag[1].reads, [resource])
        self.assertEqual(dag[1].depends_on, [1])

    def test_shell_relative_read_after_redirected_write_creates_dependency(self):
        steps = [
            ActionStep(1, "shell", "echo report > ./reports/result.txt", "write"),
            ActionStep(2, "shell", "Get-Content reports\\result.txt", "read"),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[0].writes, ["file:reports/result.txt"])
        self.assertEqual(dag[1].reads, ["file:reports/result.txt"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_shell_directory_creation_serializes_descendant_redirect_for_aliases(self):
        for command in ("mkdir", "md"):
            with self.subTest(command=command):
                dag = build_dag(
                    [
                        ActionStep(1, "shell", f"{command} reports", "mkdir"),
                        ActionStep(2, "shell", "echo x > reports/result.txt", "write"),
                    ]
                )

                self.assertEqual(dag[1].depends_on, [1])

    def test_shell_copy_item_destination_is_inferred(self):
        reads, writes = extract_resources(
            "Copy-Item -Path 'source.txt' -Destination 'output.txt'", "shell"
        )

        self.assertIn("file:output.txt", writes)
        self.assertIn("file:source.txt", reads)

    def test_shell_set_content_path_after_value_is_inferred(self):
        reads, writes = extract_resources(
            "Set-Content -Value 'text' -Path 'output.txt'", "shell"
        )

        self.assertEqual(reads, [])
        self.assertIn("file:output.txt", writes)

    def test_shell_copy_item_positional_source_with_named_destination(self):
        reads, writes = extract_resources(
            "Copy-Item 'source.txt' -Destination 'output.txt'", "shell"
        )

        self.assertIn("file:source.txt", reads)
        self.assertIn("file:output.txt", writes)

    def test_redirect_operator_inside_quoted_shell_text_is_ignored(self):
        reads, writes = extract_resources("echo 'text > output.txt'", "shell")

        self.assertEqual((reads, writes), ([], []))

    def test_shell_file_descriptor_redirection_is_not_a_file_write(self):
        reads, writes = extract_resources("echo report 2>&1", "shell")

        self.assertEqual((reads, writes), ([], []))

    def test_explicit_relative_file_resource_matches_normalized_inference(self):
        steps = [
            ActionStep(1, "python", "open('reports/result.json', 'w')", "write"),
            ActionStep(
                2,
                "python",
                "consume_result()",
                "read",
                reads=["file:reports\\.\\result.json"],
            ),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[1].reads, ["file:reports/result.json"])
        self.assertEqual(dag[1].depends_on, [1])

    def test_explicit_resource_only_dependencies_are_preserved(self):
        steps = [
            ActionStep(1, "python", "produce()", "write", writes=["file:explicit.txt"]),
            ActionStep(2, "python", "consume()", "read", reads=["file:explicit.txt"]),
        ]

        dag = build_dag(steps)

        self.assertEqual(dag[1].depends_on, [1])

    def test_windows_absolute_path_inference_is_unchanged(self):
        reads, writes = extract_resources(
            "open(r'C:\\data\\input.json', 'r')", "python"
        )

        normalized_path = os.path.normpath(r"C:\data\input.json")
        resource = f"file:{normalized_path}"
        self.assertIn(resource, reads)
        self.assertNotIn(resource, writes)

    def test_desktop_state_is_still_serialized(self):
        steps = [
            ActionStep(1, "python", "click_screen(10, 20)", "click"),
            ActionStep(2, "python", "type_text('hello')", "type"),
        ]

        dag = build_dag(steps)

        self.assertIn("desktop:", dag[0].writes)
        self.assertEqual(dag[1].depends_on, [1])

    def test_filename_like_strings_without_file_io_context_are_ignored(self):
        python_reads, python_writes = extract_resources("print('report.txt')", "python")
        shell_reads, shell_writes = extract_resources(
            "Write-Output '%REPORT_PATH%'", "shell"
        )
        dynamic_reads, dynamic_writes = extract_resources(
            "open(os.path.join(base_dir, 'report.txt'), 'w')", "python"
        )

        self.assertEqual((python_reads, python_writes), ([], []))
        self.assertEqual((shell_reads, shell_writes), ([], []))
        self.assertEqual((dynamic_reads, dynamic_writes), ([], []))

    def test_network_resource_inference_is_unchanged(self):
        reads, writes = extract_resources("requests.get('https://Example.test/path')", "python")

        self.assertEqual(reads, ["net:example.test"])
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
