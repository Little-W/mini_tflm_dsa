// Shared combinational definitions, included inside each standalone module.
// Records and vectors are little endian: byte/lane zero occupies the low bits.
function automatic integer pcr_pop16(input logic [15:0] value);
 integer i; begin pcr_pop16=0;for(i=0;i<16;i=i+1)pcr_pop16=pcr_pop16+integer'(value[i]);end
endfunction
function automatic integer pcr_ctz32(input logic [31:0] value);
 integer i;logic found;begin
  pcr_ctz32=32;found=0;
  for(i=0;i<32;i=i+1)if(value[i] && !found)begin pcr_ctz32=i;found=1;end
 end
endfunction
function automatic logic pcr_fits(input logic signed [31:0] value,input integer width);
 logic signed[31:0] shifted;begin
  shifted=0;
  if(width==0)pcr_fits=value==0;
  else if(width==32)pcr_fits=1;
  else begin shifted=value<<(32-width);pcr_fits=(shifted>>>(32-width))==value;end
 end
endfunction
function automatic logic[31:0] pcr_lowmask(input integer width);
 begin
  if(width==0)pcr_lowmask=0;
  else if(width>=32)pcr_lowmask=32'hffffffff;
  else pcr_lowmask=(32'd1<<width)-1'b1;
 end
endfunction
function automatic logic[3:0] pcr_wordmask(input logic[6:0] bytes);
 integer i;begin
  pcr_wordmask=0;
  for(i=0;i<4;i=i+1)if(16*i<integer'(bytes))pcr_wordmask[i]=1;
 end
endfunction

// Select at most two complete lane values. The mask is one/two-hot for
// legal exception records; no per-lane variable 512-bit windows are used.
function automatic logic[63:0] pcr_gather_two(input logic[511:0] data,input logic[15:0] mask);
 logic seen;logic[63:0] pair;integer l;begin
  seen=0;pair=0;
  for(l=0;l<16;l=l+1)begin
   if(mask[l] && !seen)pair[31:0]=data[l*32+:32];
   if(mask[l] && seen)pair[63:32]=data[l*32+:32];
   seen=seen|mask[l];
  end
  pcr_gather_two=pair;
 end
endfunction
// A single byte-aligned window supplies both possible patches. Logical
// shifting supplies explicit zeros beyond byte 63 (e=1 at byte60, e=0 at64).
function automatic logic[63:0] pcr_patch_window(input logic[511:0] record_bits,input logic[6:0] byte_offset);
 logic[511:0] shifted;begin
  shifted=record_bits>>{byte_offset,3'b000};pcr_patch_window=shifted[63:0];
 end
endfunction
// Insert one contiguous 32/64-bit patch stream, not sixteen dynamic inserts.
function automatic logic[511:0] pcr_put_patches(input logic[511:0] record_bits,input logic[6:0] byte_offset,
                                               input logic[63:0] pair,input logic have0,have1);
 logic[511:0] data_bits,mask_bits;begin
  data_bits=0;mask_bits=0;
  if(have0)begin data_bits[31:0]=pair[31:0];mask_bits[31:0]=32'hffffffff;end
  if(have1)begin data_bits[63:32]=pair[63:32];mask_bits[63:32]=32'hffffffff;end
  data_bits=data_bits<<{byte_offset,3'b000};mask_bits=mask_bits<<{byte_offset,3'b000};
  pcr_put_patches=(record_bits&~mask_bits)|data_bits;
 end
endfunction

// [519]=candidate (0 means RAW); [518:512]=byte length; [511:0]=record.
function automatic logic[519:0] pcr_encode(input logic[511:0] data);
 logic[31:0] magnitude[0:15];
 logic signed[31:0] difference[0:15];
 logic[31:0] first0,first1,first2,anchor,value,low_mask;
 logic[15:0] active,signs,exceptions,best_exceptions;
 logic signed[31:0] quotient;
 logic[511:0] record_bits,compact_stream;
 logic[31:0] compact_q[0:15];
 logic[3:0] lane_rank[0:15];
 logic[3:0] rank_count;
 logic[63:0] patches;
 logic[6:0] patch_byte;
 integer n,seen,l,c,j,t,min0,min1,min2,shift,width,ne,bytes;
 integer best_bytes,best_width,best_shift;
 begin
  active=0;signs=0;n=0;seen=0;first0=0;first1=0;first2=0;anchor=0;
  for(l=0;l<16;l=l+1)begin
   value=data[l*32+:32];active[l]=value!=0;signs[l]=value[31];
   magnitude[l]=value[31]?(~value+32'd1):value;
   difference[l]=0;
   if(value!=0)begin
    n=n+1;
    if(seen==0)first0=magnitude[l];
    if(seen==1)first1=magnitude[l];
    if(seen==2)first2=magnitude[l];
    seen=seen+1;
   end
  end
  anchor=first0;
  if(n>=3)begin
   if(first0<=first1)begin
    if(first1<=first2)anchor=first1;
    else if(first0<=first2)anchor=first2;else anchor=first0;
   end else begin
    if(first0<=first2)anchor=first0;
    else if(first1<=first2)anchor=first2;else anchor=first1;
   end
  end
  min0=32;min1=32;min2=32;
  for(l=0;l<16;l=l+1)begin
   if(active[l])difference[l]=$signed(magnitude[l]-anchor);
   t=active[l]?pcr_ctz32(difference[l]):32;
   if(t<min0)begin min2=min1;min1=min0;min0=t;end
   else if(t<min1)begin min2=min1;min1=t;end
   else if(t<min2)min2=t;
  end
  best_bytes=65;best_width=32;best_shift=31;best_exceptions=0;
  exceptions=0;quotient=0;shift=0;width=0;ne=0;bytes=0;low_mask=0;
  // At most four factors. Duplicate values are harmless: the exact tie rule
  // chooses the same record, with no dynamic sort or loop bound.
  for(c=0;c<4;c=c+1)begin
   case(c)0:shift=0;1:shift=min0;2:shift=min1;default:shift=min2;endcase
   if(shift>31)shift=31;
   low_mask=pcr_lowmask(shift);
   for(j=0;j<9;j=j+1)begin
    width=j*4;ne=0;exceptions=0;
    for(l=0;l<16;l=l+1)begin
     quotient=difference[l]>>>shift;
     if(active[l] && (((difference[l]&low_mask)!=0) || !pcr_fits(quotient,width)))begin
      exceptions[l]=1;ne=ne+1;
     end
    end
    bytes=12+(n*width+7)/8+4*ne;
    if(ne<=2 && bytes<=64 &&
       (bytes<best_bytes || (bytes==best_bytes &&
        (width<best_width || (width==best_width && shift<best_shift)))))begin
     best_bytes=bytes;best_width=width;best_shift=shift;best_exceptions=exceptions;
    end
   end
  end
  // Rank-gather 32-bit q values, then pack by constant field positions for
  // each of the nine legal widths. The only variable record insertion is
  // the shared stream of at most two full-width patches.
  rank_count=0;patches=0;patch_byte=0;compact_stream=0;record_bits=data;
  for(l=0;l<16;l=l+1)begin
   lane_rank[l]=rank_count;if(active[l])rank_count=rank_count+1'b1;
  end
  for(j=0;j<16;j=j+1)begin
   compact_q[j]=0;
   for(l=0;l<16;l=l+1)if(active[l] && lane_rank[l]==4'(j))compact_q[j]=difference[l]>>>best_shift;
  end
  case(best_width)
   4:for(j=0;j<16;j=j+1)compact_stream[j*4+:4]=compact_q[j][3:0];
   8:for(j=0;j<16;j=j+1)compact_stream[j*8+:8]=compact_q[j][7:0];
   12:for(j=0;j<16;j=j+1)compact_stream[j*12+:12]=compact_q[j][11:0];
   16:for(j=0;j<16;j=j+1)compact_stream[j*16+:16]=compact_q[j][15:0];
   20:for(j=0;j<16;j=j+1)compact_stream[j*20+:20]=compact_q[j][19:0];
   24:for(j=0;j<16;j=j+1)compact_stream[j*24+:24]=compact_q[j][23:0];
   28:for(j=0;j<16;j=j+1)compact_stream[j*28+:28]=compact_q[j][27:0];
   32:for(j=0;j<16;j=j+1)compact_stream[j*32+:32]=compact_q[j];
   default:compact_stream=0;
  endcase
  pcr_encode={1'b0,7'd64,data};
  if(best_bytes<=64)begin
   record_bits={compact_stream[415:0],96'd0};
   record_bits[15:0]=active;record_bits[31:16]=signs;record_bits[63:32]=anchor;
   record_bits[79:64]=best_exceptions;
   record_bits[84:80]=5'(best_shift);record_bits[90:85]=6'(best_width);
   patches=pcr_gather_two(data,best_exceptions);patch_byte=7'(12+(n*best_width+7)/8);
   ne=pcr_pop16(best_exceptions);
   record_bits=pcr_put_patches(record_bits,patch_byte,patches,ne>=1,ne>=2);
   pcr_encode={1'b1,7'(best_bytes),record_bits};
  end
 end
endfunction

function automatic logic[511:0] pcr_decode(input logic candidate,input logic[511:0] record_bits);
 logic[15:0] active,signs,exceptions;
 logic[31:0] anchor,magnitude,restored;
 logic signed[31:0] compact_q[0:15];
 logic signed[31:0] quotient;
 logic[607:0] padded_record;
 logic[511:0] result;
 logic[63:0] patches;
 logic[6:0] patch_byte;
 logic[3:0] rank_count;
 logic seen_exception;
 integer l,j,n,width,shift;
 begin
  active=record_bits[15:0];signs=record_bits[31:16];anchor=record_bits[63:32];exceptions=record_bits[79:64];
  shift=integer'(record_bits[84:80]);width=integer'(record_bits[90:85]);n=pcr_pop16(active);
  // A legal <=64-byte record never selects the padded compact slots:
  // width28 allows at most14 active slots; width32 at most13 (fewer with E).
  padded_record={96'd0,record_bits};result=0;rank_count=0;seen_exception=0;
  magnitude=0;restored=0;quotient=0;patch_byte=7'(12+(n*width+7)/8);
  patches=pcr_patch_window(record_bits,patch_byte);
  for(j=0;j<16;j=j+1)compact_q[j]=0;
  case(width)
   4:for(j=0;j<16;j=j+1)compact_q[j]={{28{padded_record[96+j*4+3]}},padded_record[96+j*4+:4]};
   8:for(j=0;j<16;j=j+1)compact_q[j]={{24{padded_record[96+j*8+7]}},padded_record[96+j*8+:8]};
   12:for(j=0;j<16;j=j+1)compact_q[j]={{20{padded_record[96+j*12+11]}},padded_record[96+j*12+:12]};
   16:for(j=0;j<16;j=j+1)compact_q[j]={{16{padded_record[96+j*16+15]}},padded_record[96+j*16+:16]};
   20:for(j=0;j<16;j=j+1)compact_q[j]={{12{padded_record[96+j*20+19]}},padded_record[96+j*20+:20]};
   24:for(j=0;j<16;j=j+1)compact_q[j]={{8{padded_record[96+j*24+23]}},padded_record[96+j*24+:24]};
   28:for(j=0;j<16;j=j+1)compact_q[j]={{4{padded_record[96+j*28+27]}},padded_record[96+j*28+:28]};
   32:for(j=0;j<16;j=j+1)compact_q[j]=padded_record[96+j*32+:32];
   default:begin end
  endcase
  if(!candidate)result=record_bits;
  else begin
   for(l=0;l<16;l=l+1)if(active[l])begin
    quotient=compact_q[rank_count];rank_count=rank_count+1'b1;
    // Exact in Z/(2^32): only final low bits are consumed. This is equivalent
    // to the original signed64 shift/add followed by low32 and polarity.
    magnitude=anchor+(quotient<<shift);
    restored=signs[l]?(32'd0-magnitude):magnitude;
    if(exceptions[l])begin
     restored=seen_exception?patches[63:32]:patches[31:0];seen_exception=1;
    end
    result[l*32+:32]=restored;
   end
  end
  pcr_decode=result;
 end
endfunction

// [520:517]=full-old-record read mask; [516:513]=fast write mask;
// [512]=hit; [511:0]=updated record (unchanged on a miss).
function automatic logic[520:0] pcr_fast(input logic candidate,input logic[6:0] length,
                                        input logic[511:0] record_bits,input logic[511:0] delta);
 logic[15:0] active,signs,exceptions,normal;
 logic[31:0] anchor;
 logic[63:0] patch_pair,patch_deltas,updated_pair;
 logic[6:0] patch_byte;
 logic signed[63:0] lane_delta,normalized,common,next_anchor,lower,upper,limit;
 logic have_common,common_ok,inactive_ok,any_positive,format_ok,hit;
 logic[3:0] read_mask,write_mask;
 logic[511:0] result;
 integer l,n,ne,width,shift,b,total_bytes;
 begin
  active=record_bits[15:0];signs=record_bits[31:16];anchor=record_bits[63:32];exceptions=record_bits[79:64];
  normal=active&~exceptions;shift=integer'(record_bits[84:80]);width=integer'(record_bits[90:85]);
  n=pcr_pop16(active);ne=pcr_pop16(exceptions);
  total_bytes=12+(n*width+7)/8+4*ne;
  format_ok=candidate && record_bits[95:91]==0 && (exceptions&~active)==0 && ne<=2 && width<=32 && (width%4)==0 && total_bytes==integer'(length) && total_bytes<=64;
  have_common=0;common_ok=1;inactive_ok=1;any_positive=0;common=0;lane_delta=0;normalized=0;
  for(l=0;l<16;l=l+1)begin
   lane_delta={{32{delta[l*32+31]}},delta[l*32+:32]};
   if(!active[l] && lane_delta!=0)inactive_ok=0;
   if(normal[l])begin
    normalized=signs[l]?-lane_delta:lane_delta;
    if(!have_common)begin common=normalized;have_common=1;end
    else if(normalized!=common)common_ok=0;
    if(!signs[l])any_positive=1;
   end
  end
  next_anchor=$signed({32'd0,anchor})+common;lower=next_anchor;upper=next_anchor;
  // w<=32,s<=31 => largest exponent is 62. Signed64 is required here.
  if(width>0 && width<=32)begin
   lower=next_anchor-(64'sd1<<(width-1+shift));
   upper=next_anchor+(((64'sd1<<(width-1))-64'sd1)<<shift);
  end
  limit=any_positive?64'sd2147483647:64'sd2147483648;
  hit=format_ok && have_common && common_ok && inactive_ok && lower>=0 && upper<=limit;
  result=record_bits;read_mask=pcr_wordmask(length);write_mask=0;
  patch_byte=7'(12+(n*width+7)/8);
  patch_pair=pcr_patch_window(record_bits,patch_byte);patch_deltas=pcr_gather_two(delta,exceptions);
  updated_pair[31:0]=patch_pair[31:0]+patch_deltas[31:0];
  updated_pair[63:32]=patch_pair[63:32]+patch_deltas[63:32];
  if(hit)begin
   result[63:32]=next_anchor[31:0];write_mask[0]=1;
   result=pcr_put_patches(result,patch_byte,updated_pair,ne>=1,ne>=2);
   for(b=0;b<4;b=b+1)begin
    if(ne>=1 && (integer'(patch_byte)/16==b || (integer'(patch_byte)+3)/16==b))write_mask[b]=1;
    if(ne>=2 && ((integer'(patch_byte)+4)/16==b || (integer'(patch_byte)+7)/16==b))write_mask[b]=1;
   end
  end
  pcr_fast={read_mask,write_mask,hit,result};
 end
endfunction
