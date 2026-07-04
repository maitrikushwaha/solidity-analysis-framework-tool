pragma solidity ^0.4.25;

contract Crowdsale {

  function buyTokens() public payable {
    uint shipAmount = block.timestamp;
    require(shipAmount > 0);
    return;
  }
}