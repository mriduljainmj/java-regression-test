package com.example.products;

import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class OrderService {

    // Bulk discount tiers: 50+ units -> 10%, 10+ units -> 5%.
    private static final int LARGE_TIER_QUANTITY = 50;
    private static final int SMALL_TIER_QUANTITY = 10;
    private static final double LARGE_TIER_DISCOUNT = 0.10;
    private static final double SMALL_TIER_DISCOUNT = 0.05;

    // Orders above this total (after discount) are rejected.
    private static final double MAX_ORDER_TOTAL = 5000.00;

    private final ProductService productService;
    private final Map<Long, Order> store = new ConcurrentHashMap<>();
    private final AtomicLong sequence = new AtomicLong(0);

    public OrderService(ProductService productService) {
        this.productService = productService;
    }

    public Order create(OrderRequest request) {
        Product product = productService.findById(request.getProductId());
        int quantity = request.getQuantity();

        double discount = 0.0;
        if (quantity >= LARGE_TIER_QUANTITY) {
            discount = LARGE_TIER_DISCOUNT;
        } else if (quantity >= SMALL_TIER_QUANTITY) {
            discount = SMALL_TIER_DISCOUNT;
        }

        double total = round2(product.getPrice() * quantity * (1 - discount));
        if (total > MAX_ORDER_TOTAL) {
            throw new OrderLimitExceededException(total);
        }

        long id = sequence.incrementAndGet();
        Order order = new Order(id, product.getId(), quantity, product.getPrice(),
                discount * 100, total);
        store.put(id, order);
        return order;
    }

    public boolean hasOrdersForProduct(Long productId) {
        return store.values().stream().anyMatch(o -> o.getProductId().equals(productId));
    }

    public Order findById(Long id) {
        Order order = store.get(id);
        if (order == null) {
            throw new OrderNotFoundException(id);
        }
        return order;
    }

    public void clear() {
        store.clear();
    }

    private static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
