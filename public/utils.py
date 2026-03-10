def pagination_data(paginator):
    page = paginator.page
    return {
        "count":       page.paginator.count,
        "total_pages": page.paginator.num_pages,
        "page":        page.number,
        "next":        page.next_page_number()     if page.has_next()     else None,
        "previous":    page.previous_page_number() if page.has_previous() else None,
    }