pragma solidity ^0.4.25;

contract TokenVesting {
  uint256 public cliff;

  function vestedAmount() public view returns (uint256) {
     if (block.timestamp < cliff) {
        return cliff;
     }
  }
}