pragma solidity ^0.4.25;

contract SaiVox {

    function era() public view returns (uint) {
        return block.timestamp;
    }
}
