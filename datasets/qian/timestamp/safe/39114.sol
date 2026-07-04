pragma solidity ^0.4.25;

contract ICO {

    uint public priceToBuyInFinney;
    mapping (uint => uint[3]) public priceChange;

    function ICO() {
        priceToBuyInFinney = 0;
        priceChange[0] = [priceToBuyInFinney, block.number, block.timestamp];
        return;
    }
}