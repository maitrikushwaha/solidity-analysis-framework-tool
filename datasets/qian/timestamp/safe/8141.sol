pragma solidity ^0.4.25;

contract Inner4WithEth {
    uint256 someValue;

    function doSomething() public payable {
        someValue = block.timestamp;
    }
}