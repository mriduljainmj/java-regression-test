import tempfile
import unittest
from pathlib import Path

from testgen.ado import criteria_coverage_report


class AdoCoverageReportTest(unittest.TestCase):
    def test_changed_file_contents_count_as_coverage_evidence(self):
        acceptance_criteria = (
            "When a request is made to discount-policy in PricingOrchestrationController, "
            "the system should return LoyaltyDiscountPercent as 9 for loyalty members and 0 "
            "for non-loyalty members.\n\n"
            "The returned TotalDiscountPercent must include the loyalty discount with the "
            "base discount, and order-total-from-policy must use that updated total discount "
            "to calculate DiscountAmount and FinalTotal.\n\n"
            "PolicyVersion should remain unchanged, and existing validation behavior for "
            "invalid quantity or unit price should continue to work as before."
        )

        controller_path = "dotnet-component/Controllers/PricingOrchestrationController.cs"
        controller_content = """using System;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

namespace BP.Controllers
{
    [ApiController]
    [Route(\"api\")]
    public class PricingOrchestrationController : ControllerBase
    {
        [HttpGet(\"discount-policy\")]
        public ActionResult<DiscountPolicyResponse> GetDiscountPolicy([FromQuery] int quantity, [FromQuery] bool isLoyaltyMember = false)
        {
            if (quantity <= 0)
                return BadRequest(new { message = \"Quantity must be greater than 0.\" });

            int baseDiscountPercent = quantity >= 50 ? 18 : quantity >= 25 ? 15 : quantity >= 10 ? 8 : 0;
            int loyaltyDiscountPercent = isLoyaltyMember ? 9 : 0;
            int totalDiscountPercent = Math.Min(100, baseDiscountPercent + loyaltyDiscountPercent);

            return Ok(new DiscountPolicyResponse
            {
                LoyaltyDiscountPercent = loyaltyDiscountPercent,
                TotalDiscountPercent = totalDiscountPercent,
                PolicyVersion = \"v1\"
            });
        }

        [HttpPost(\"order-total-from-policy\")]
        public IActionResult CalculateOrderTotalFromPolicy([FromBody] OrderTotalFromPolicyRequest request)
        {
            if (request == null || request.Quantity <= 0 || request.UnitPrice <= 0)
                return BadRequest(new { message = \"UnitPrice and Quantity must be greater than 0.\" });

            decimal discountAmount = 0m;
            decimal finalTotal = 0m;
            return Ok(new OrderTotalFromPolicyResponse
            {
                TotalDiscountPercent = 9,
                DiscountAmount = discountAmount,
                FinalTotal = finalTotal,
                PolicyVersion = \"v1\"
            });
        }
    }
}
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            target = repo_root / controller_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(controller_content, encoding="utf-8")

            report = criteria_coverage_report(
                acceptance_criteria=acceptance_criteria,
                git_diff='-            int loyaltyDiscountPercent = isLoyaltyMember ? 12 : 0;\n+            int loyaltyDiscountPercent = isLoyaltyMember ? 9 : 0;\n',
                changed_files=[controller_path],
                repo_root=str(repo_root),
            )

        self.assertTrue(report["covered"])
        self.assertEqual(report["missing"], [])


if __name__ == "__main__":
    unittest.main()
