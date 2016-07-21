angular.module('aiddataDET')
<<<<<<< HEAD
.controller('FiltersCtrl', function($scope, $rootScope, $log, queryFactory, $stateParams, $state, filters, filterOptions) {

  // $scope.filterOptions = { Options for a particular filter field };
  // $scope.filters = { Active Filters };
  // $scope.dataset = { Current Dataset Information }
=======
.controller('FiltersCtrl', function($scope, $rootScope, $log, queryFactory, $stateParams, $state) {
  $scope.dataset = {};
  $scope.filterOptions = {};
  $scope.filters = queryFactory.filters;
>>>>>>> 791f1b6f71bf3fbdd9ae4cff2e75cdec2fb6b4d0

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options', searchFilter: '' },
    'donors': { text: 'Donors', type: 'options', searchFilter: '' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    queryFactory.updateFilters()
      .then(function(filterOptions) {
        $scope.filterOptions = filterOptions;
        broadcastUpdates();
      });
  };

  $scope.toggleFilter = function (filter, option) {
    var checked = $scope.filters[filter] && $scope.filters[filter].indexOf(option) >= 0;
    return !checked ? queryFactory.toggleFilterOn(filter, option) :
      queryFactory.toggleFilterOff(filter, option);
  };

  $scope.toggleAll = function (filter) {
    queryFactory.resetFilter(filter);
  };

<<<<<<< HEAD
  // $rootScope.$on('dataset:selected', function(e, data) {
  //   // $scope.dataset = data;
  //   // _.each($scope.filters, function(options, filter) {
  //   //   $scope.toggleAll(filter);
  //   // });
  //   //
  //   // queryFactory.setDataset(data.name);
  // });
=======
  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    _.each($scope.filters, function(options, filter) {
      $scope.toggleAll(filter);
    });

    queryFactory.setDataset(data.name);
  });
>>>>>>> 791f1b6f71bf3fbdd9ae4cff2e75cdec2fb6b4d0

  $scope.$watch('filters', function(newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue)) {
      $scope.updateFilters();
    }
  }, true);

<<<<<<< HEAD

  $scope.$on('$viewContentLoaded', function(event){
    $scope.filterOptions = filterOptions;
    $scope.filters = filters;
    $scope.dataset = queryFactory.getDataset($stateParams.dataset);
    broadcastUpdates();
  });

  function broadcastUpdates () {
    if ($scope.filterOptions.filterTypes.indexOf('years')) {
      $scope.filterOptions.distinct.years = _.cloneDeep($scope.dataset.years);
    }

    $rootScope.$broadcast('filters:updated', filterOptions);
  }
=======
>>>>>>> 791f1b6f71bf3fbdd9ae4cff2e75cdec2fb6b4d0

});
