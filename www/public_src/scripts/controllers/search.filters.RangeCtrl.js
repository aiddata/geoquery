angular.module('aiddataDET')
.controller('RangeCtrl', function($scope, $rootScope, $log) {
  // $scope.filterData
  // $scope.filterOptions
  // $scope.activeFilters

  $scope.range = {
    min: _.min($scope.filterOptions),
    max: _.max($scope.filterOptions)
  };

  $scope.sliderOptions = {
    floor: _.min($scope.filterOptions),
    ceil: _.max($scope.filterOptions)
  };

  $scope.fields = [
    {
      text: 'min',
      validate: function (val) {
        $scope.range.min = val >= $scope.range.max ? $scope.range.max - 1 :
          val < _.min($scope.filterOptions) ? _.min($scope.filterOptions) : val;
      }
    },
    {
      text: 'max',
      validate: function (val) {
        $scope.range.max = val <= $scope.range.min ? $scope.range.min + 1 :
          val > _.max($scope.filterOptions) ? _.max($scope.filterOptions) : val;
      }
    }
  ];

});
