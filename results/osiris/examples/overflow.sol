pragma solidity ^0.4.21;
contract FeeAccumulator {
    uint8 public fee = 3;
    function applyCompoundFee(uint8 periods) external returns (uint8) {
        for (uint8 i = 0; i < periods; i++) {
            fee = fee * 3;
        }
        return fee;
    }
}