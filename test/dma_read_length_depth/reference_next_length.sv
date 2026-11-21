        end else begin : g_next_length
            assign rd_segment_len[segment] = page_limited ? page_len :
                (burst_limited ? 8'(MAX_BURST_BEATS-1) : remaining_len);
        end
