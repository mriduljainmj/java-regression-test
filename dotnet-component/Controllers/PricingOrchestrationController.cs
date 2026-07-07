using System;
using System.ComponentModel.DataAnnotations;
using System.Net.Http.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

namespace BP.Controllers
{
    [ApiController]
    [Route("api")]
    public class PricingOrchestrationController : ControllerBase
    {
        private readonly IHttpClientFactory _httpClientFactory;

        public PricingOrchestrationController(IHttpClientFactory httpClientFactory)
        {
            _httpClientFactory = httpClientFactory;
        }

        // API B: source-of-truth policy endpoint.
        [HttpGet("discount-policy")]
        [ProducesResponseType(typeof(DiscountPolicyResponse), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public ActionResult<DiscountPolicyResponse> GetDiscountPolicy([FromQuery] int quantity, [FromQuery] bool isLoyaltyMember = false)
        {
            if (quantity <= 0)
                return BadRequest(new { message = "Quantity must be greater than 0." });

            int baseDiscountPercent = quantity >= 50 ? 15 : quantity >= 25 ? 10 : quantity >= 10 ? 5 : 0;
            int loyaltyDiscountPercent = isLoyaltyMember ? 5 : 0;
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

        // API A: calls API B and computes total using B's response.
        [HttpPost("order-total-from-policy")]
        [ProducesResponseType(typeof(OrderTotalFromPolicyResponse), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        [ProducesResponseType(StatusCodes.Status502BadGateway)]
        public async Task<IActionResult> CalculateOrderTotalFromPolicy([FromBody] OrderTotalFromPolicyRequest request, CancellationToken cancellationToken)
        {
            if (request == null || request.Quantity <= 0 || request.UnitPrice <= 0)
                return BadRequest(new { message = "UnitPrice and Quantity must be greater than 0." });

            string baseUrl = $"{Request.Scheme}://{Request.Host}";
            string policyUrl = $"{baseUrl}/api/discount-policy?quantity={request.Quantity}&isLoyaltyMember={request.IsLoyaltyMember.ToString().ToLowerInvariant()}";

            var client = _httpClientFactory.CreateClient();
            var policyResponse = await client.GetAsync(policyUrl, cancellationToken);
            if (!policyResponse.IsSuccessStatusCode)
            {
                return StatusCode(StatusCodes.Status502BadGateway, new
                {
                    message = "Failed to fetch discount policy from API B.",
                    upstreamStatus = (int)policyResponse.StatusCode
                });
            }

            var policy = await policyResponse.Content.ReadFromJsonAsync<DiscountPolicyResponse>(cancellationToken: cancellationToken);
            if (policy == null)
                return StatusCode(StatusCodes.Status502BadGateway, new { message = "Invalid discount policy response from API B." });

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
        [Range(0.01, double.MaxValue, ErrorMessage = "UnitPrice must be greater than 0")]
        public decimal UnitPrice { get; set; }

        [Range(1, int.MaxValue, ErrorMessage = "Quantity must be greater than 0")]
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