"""Tests for the ADO ticket-context helpers (no network — parsing only)."""

import unittest

from testgen import ado


class WorkItemIdTest(unittest.TestCase):
    def test_extracts_ab_and_hash_refs(self):
        msg = "feat: cap price\n\nImplements AB#1234 and relates to #56."
        self.assertEqual(ado.extract_work_item_ids(msg), ["1234", "56"])

    def test_dedupes_and_handles_none(self):
        self.assertEqual(ado.extract_work_item_ids("AB#7 again AB#7"), ["7"])
        self.assertEqual(ado.extract_work_item_ids(""), [])
        self.assertEqual(ado.extract_work_item_ids(None), [])


class HtmlToTextTest(unittest.TestCase):
    def test_strips_tags_and_unescapes(self):
        html = "<div>Price cap is <b>100&nbsp;000</b>.<br>Reject above it.</div>"
        text = ado.html_to_text(html)
        self.assertIn("Price cap is 100\xa0000.", text.replace("\n", " "))
        self.assertNotIn("<", text)

    def test_list_items_become_bullets(self):
        html = "<ul><li>one</li><li>two</li></ul>"
        text = ado.html_to_text(html)
        self.assertIn("- one", text)
        self.assertIn("- two", text)

    def test_empty(self):
        self.assertEqual(ado.html_to_text(""), "")
        self.assertEqual(ado.html_to_text(None), "")


SAMPLE = {
    "id": 1234,
    "fields": {
        "System.WorkItemType": "User Story",
        "System.Title": "Cap product price",
        "System.State": "Active",
        "System.Description": "<div>Products must not exceed <b>100000</b>.</div>",
        "Microsoft.VSTS.Common.AcceptanceCriteria":
            "<ul><li>100000 is accepted</li><li>100001 returns 400</li></ul>",
    },
}


class ParseWorkItemTest(unittest.TestCase):
    def test_parses_fields_to_plain_text(self):
        wi = ado._parse_work_item(SAMPLE)
        self.assertEqual(wi["id"], 1234)
        self.assertEqual(wi["type"], "User Story")
        self.assertEqual(wi["title"], "Cap product price")
        self.assertIn("must not exceed 100000", wi["description"])
        self.assertIn("- 100001 returns 400", wi["acceptance_criteria"])

    def test_parses_comments(self):
        payload = {"comments": [
            {"text": "<p>Use 100000 exactly, not 99999.</p>",
             "createdBy": {"displayName": "Reviewer A"}},
            {"text": "", "createdBy": {"displayName": "Bot"}},  # empty skipped
        ]}
        comments = ado._parse_comments(payload)
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0].startswith("Reviewer A: "))
        self.assertIn("100000 exactly", comments[0])


class FormatTest(unittest.TestCase):
    def test_format_ticket_context(self):
        rendered = ado.format_ticket_context([ado._parse_work_item(SAMPLE)])
        self.assertIn("Work item #1234 [User Story] — Cap product price", rendered)
        self.assertIn("Acceptance criteria:", rendered)

    def test_empty_is_not_provided(self):
        self.assertEqual(ado.format_ticket_context([]), "Not provided.")
        self.assertEqual(ado.format_ticket_context([{}]), "Not provided.")

    def test_collect_reviewer_comments(self):
        wi = {"comments": ["A: x", "B: y"]}
        self.assertEqual(ado.collect_reviewer_comments([wi, {}]), ["A: x", "B: y"])


if __name__ == "__main__":
    unittest.main()
