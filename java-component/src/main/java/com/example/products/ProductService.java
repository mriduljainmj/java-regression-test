package com.example.products;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class ProductService {

    private final Map<Long, Product> store = new ConcurrentHashMap<>();
    private final AtomicLong sequence = new AtomicLong(0);

    public List<Product> findAll() {
        return List.copyOf(store.values());
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
        product.setName("NewUpdatedProduct" +request.getName());
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
