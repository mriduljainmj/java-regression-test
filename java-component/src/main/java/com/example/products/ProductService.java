package com.example.products;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

@Service
public class ProductService {

    // A single update may not raise the price by more than 50%.
    private static final double MAX_PRICE_INCREASE_FACTOR = 1.5;

    private final Map<Long, Product> store = new ConcurrentHashMap<>();
    private final AtomicLong sequence = new AtomicLong(0);

    public List<Product> findAll(Double minPrice, Double maxPrice) {
        if (minPrice != null && maxPrice != null && minPrice > maxPrice) {
            throw new InvalidPriceRangeException(minPrice, maxPrice);
        }
        return store.values().stream()
                .filter(p -> minPrice == null || p.getPrice() >= minPrice)
                .filter(p -> maxPrice == null || p.getPrice() <= maxPrice)
                .collect(Collectors.toList());
    }

    public Product findById(Long id) {
        Product product = store.get(id);
        if (product == null) {
            throw new ProductNotFoundException(id);
        }
        return product;
    }

    public Product create(ProductRequest request) {
        long id = sequence.incrementAndGet();
        Product product = new Product(id, request.getName(), request.getPrice());
        store.put(id, product);
        return product;
    }

    public Product update(Long id, ProductRequest request) {
        Product product = findById(id);
        if (request.getPrice() > product.getPrice() * MAX_PRICE_INCREASE_FACTOR) {
            throw new PriceIncreaseExceededException(product.getPrice(), request.getPrice());
        }
        product.setName(request.getName());
        product.setPrice(request.getPrice());
        return product;
    }

    public void delete(Long id) {
        if (store.remove(id) == null) {
            throw new ProductNotFoundException(id);
        }
    }

    public void clear() {
        store.clear();
    }
}
