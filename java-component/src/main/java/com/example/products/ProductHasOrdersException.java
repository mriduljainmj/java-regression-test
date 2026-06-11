package com.example.products;

public class ProductHasOrdersException extends RuntimeException {

    public ProductHasOrdersException(Long productId) {
        super("Product " + productId + " has orders and cannot be deleted");
    }
}
