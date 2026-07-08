using System;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

namespace BP.Controllers
{
    [ApiController]
    [Route("api")]
    public class PricingOrchestrationController : ControllerBase
    {
        public PricingOrchestrationController() { }

        // API B: source-of-truth policy endpoint.
        [HttpGet("discount-policy")]
        [ProducesResponseType(typeof(DiscountPolicyResponse), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public ActionResult<DiscountPolicyResponse> GetDiscountPolicy([FromQuery] int quantity, [FromQuery] bool isLoyaltyMember = false)
        {
            if (quantity <= 0)
                return BadRequest(new { message = "Quantity must be greater than 0." });

            int baseDiscountPercent = quantity >= 50 ? 18 : quantity >= 25 ? 12 : quantity >= 10 ? 6 : 0;
            int loyaltyDiscountPercent = isLoyaltyMember ? 7 : 0;
            int totalDiscountPercent = Math.Min(100, baseDiscountPercent + loyaltyDiscountPercent);

            return Ok(new DiscountPolicyResponse
            {
                Quantity = quantity,
                IsLoyaltyMember = isLoyaltyMember,
                BaseDiscountPercent = baseDiscountPercent,
                LoyaltyDiscountPercent = loyaltyDiscountPercent,
                TotalDiscountPercent = totalDiscountPercent,
                PolicyVersion = "v1"
            });
        }

        // API A: consumes API B response shape and computes total from that policy.
        [HttpPost("order-total-from-policy")]
        [ProducesResponseType(typeof(OrderTotalFromPolicyResponse), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public IActionResult CalculateOrderTotalFromPolicy([FromBody] OrderTotalFromPolicyRequest request)
        {
            if (request == null || request.Quantity <= 0 || request.UnitPrice <= 0)
                return BadRequest(new { message = "UnitPrice and Quantity must be greater than 0." });

            var policyResult = GetDiscountPolicy(request.Quantity, request.IsLoyaltyMember);
            var okResult = policyResult.Result as OkObjectResult;
            if (okResult?.Value is not DiscountPolicyResponse policy)
                return BadRequest(new { message = "Unable to resolve discount policy from API B." });

            decimal subtotal = request.UnitPrice * request.Quantity;
            decimal discountAmount = subtotal * policy.TotalDiscountPercent / 100m;
            decimal finalTotal = subtotal - discountAmount;

            return Ok(new OrderTotalFromPolicyResponse
            {
                UnitPrice = request.UnitPrice,
                Quantity = request.Quantity,
                Subtotal = Math.Round(subtotal, 2),
                TotalDiscountPercent = policy.TotalDiscountPercent,
                DiscountAmount = Math.Round(discountAmount, 2),
                FinalTotal = Math.Round(finalTotal, 2),
                PolicyVersion = policy.PolicyVersion
            });
        }
    }

    public class DiscountPolicyResponse
    {
        public int Quantity { get; set; }
        public bool IsLoyaltyMember { get; set; }
        public int BaseDiscountPercent { get; set; }
        public int LoyaltyDiscountPercent { get; set; }
        public int TotalDiscountPercent { get; set; }
        public string PolicyVersion { get; set; } = "v1";
    }

    public class OrderTotalFromPolicyRequest
    {
        public decimal UnitPrice { get; set; }

        public int Quantity { get; set; }

        public bool IsLoyaltyMember { get; set; }
    }

    public class OrderTotalFromPolicyResponse
    {
        public decimal UnitPrice { get; set; }
        public int Quantity { get; set; }
        public decimal Subtotal { get; set; }
        public int TotalDiscountPercent { get; set; }
        public decimal DiscountAmount { get; set; }
        public decimal FinalTotal { get; set; }
        public string PolicyVersion { get; set; } = "v1";
    }
}