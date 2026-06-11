package com.example.products;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public class ReviewRequest {

    @NotNull(message = "rating is required")
    @Min(value = 2, message = "rating must be at least 2")
    @Max(value = 5, message = "rating must not exceed 5")
    private Integer rating;

    @Size(max = 200, message = "comment must not exceed 200 characters")
    private String comment;

    public Integer getRating() {
        return rating;
    }

    public void setRating(Integer rating) {
        this.rating = rating;
    }

    public String getComment() {
        return comment;
    }

    public void setComment(String comment) {
        this.comment = comment;
    }
}
