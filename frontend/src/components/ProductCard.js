import React from 'react';
import styled from 'styled-components';
import { formatPrice } from '../utils/formatPrice';

const ProductCard = ({ product, currencyCode = 'USD' }) => {
  if (!product?.url) return null;
  const priceLabel = formatPrice(
    product.price,
    product.currency || currencyCode,
  );
  const ratingLabel =
    product.rating != null && !Number.isNaN(Number(product.rating))
      ? `★ ${Number(product.rating).toFixed(1)}${product.review_count ? ` (${product.review_count})` : ''}`
      : null;
  const matchNote =
    product.match_quality && product.match_quality !== 'full'
      ? product.match_quality === 'partial'
        ? 'Close match'
        : 'Alternative'
      : null;

  return (
    <Card href={product.url} target="_blank" rel="noopener noreferrer">
      {product.image_url ? (
        <Thumb src={product.image_url} alt={product.title || 'Product'} />
      ) : (
        <ThumbPlaceholder aria-hidden="true" />
      )}
      <CardBody>
        <Title>{product.title || 'Product'}</Title>
        {product.brand ? <Meta>{product.brand}</Meta> : null}
        {ratingLabel ? <Meta>{ratingLabel}</Meta> : null}
        {matchNote ? <MatchNote>{matchNote}</MatchNote> : null}
        {priceLabel ? <Price>{priceLabel}</Price> : null}
      </CardBody>
    </Card>
  );
};

const Card = styled.a`
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(0, 0, 0, 0.08);
  text-decoration: none;
  color: inherit;
  margin-top: 8px;

  &:hover {
    border-color: var(--primary-color);
  }
`;

const Thumb = styled.img`
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 8px;
  flex-shrink: 0;
`;

const ThumbPlaceholder = styled.div`
  width: 48px;
  height: 48px;
  border-radius: 8px;
  flex-shrink: 0;
  background: rgba(0, 0, 0, 0.06);
`;

const CardBody = styled.div`
  min-width: 0;
`;

const Title = styled.div`
  font-size: 13px;
  font-weight: 600;
  line-height: 1.3;
`;

const Meta = styled.div`
  font-size: 11px;
  opacity: 0.75;
  margin-top: 2px;
`;

const Price = styled.div`
  font-size: 12px;
  font-weight: 600;
  margin-top: 4px;
  color: var(--primary-color);
`;

const MatchNote = styled.div`
  font-size: 10px;
  opacity: 0.7;
  margin-top: 2px;
  font-style: italic;
`;

export default ProductCard;
