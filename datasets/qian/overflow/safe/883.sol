pragma solidity ^0.4.25;

contract RakuRakuEth {
  function getCurrentTimestamp () external view returns (uint256) {
    return block.timestamp;
  }
}